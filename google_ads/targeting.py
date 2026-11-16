"""Compare only explicitly managed families and mutate one atomic diff."""

# GAQL uses closed field/source constants and resource literals escaped by reads.literal.

import json
from copy import deepcopy
from .accounts import get_account
from .reads import base, literal, CRITERION_FIELDS, campaign_row
from .mutations_common import campaign, complete_rows, atomic, update, conflict
from .validation import schedule, schedule_wire, reject


def canonical(value):
    value = deepcopy(value)
    if "geo_target_constants" in value:
        if len(set(value["geo_target_constants"])) != len(value["geo_target_constants"]):
            reject("Geo targets must be unique.")
        value["geo_target_constants"] = sorted(value["geo_target_constants"])
    if "schedule" in value:
        intervals = schedule(value["schedule"])
        value["schedule"] = (
            {
                "mode": "weekly",
                "intervals": sorted(intervals, key=lambda x: json.dumps(x, sort_keys=True)),
            }
            if intervals
            else {"mode": "all_time"}
        )
    return value


def snapshot(ctx, send, name, families):
    c = campaign_row(ctx, send, name)["campaign"]
    rows = complete_rows(
        ctx,
        send,
        f"SELECT {CRITERION_FIELDS} FROM campaign_criterion WHERE campaign_criterion.campaign = {literal(name)} AND campaign_criterion.type IN ('LOCATION', 'AD_SCHEDULE') AND campaign_criterion.status != 'REMOVED'",  # nosec B608
    )
    criteria = []
    value = {}
    intervals = []
    geo = []
    minute = {"ZERO": 0, "FIFTEEN": 15, "THIRTY": 30, "FORTY_FIVE": 45}
    for row in rows:
        item = row["campaignCriterion"]
        if item.get("status") == "REMOVED":
            continue
        if "location" in item and not item.get("negative", False):
            geo.append(item["location"]["geoTargetConstant"])
            criteria.append(item)
        elif "adSchedule" in item:
            s = item["adSchedule"]
            intervals.append(
                {
                    "day": s["dayOfWeek"],
                    "start_hour": s.get("startHour", 0),
                    "start_minute": minute[s.get("startMinute", "ZERO")],
                    "end_hour": s.get("endHour", 0),
                    "end_minute": minute[s.get("endMinute", "ZERO")],
                }
            )
            # ProtoJSON may omit zero-valued schedule scalars; compare canonical wire values.
            item = deepcopy(item)
            item["adSchedule"] = schedule_wire(intervals[-1])
            criteria.append(item)
    if "geo_target_constants" in families:
        if len(set(geo)) != len(geo):
            conflict("Duplicate geo criteria require resolution before this update.")
        value["geo_target_constants"] = geo
    if "schedule" in families:
        value["schedule"] = (
            {"mode": "weekly", "intervals": intervals} if intervals else {"mode": "all_time"}
        )
    if "location_options" in families:
        settings = c.get("geoTargetTypeSetting", {})
        value["location_options"] = {
            "positive_geo_target_type": settings.get("positiveGeoTargetType", "UNSPECIFIED"),
            "negative_geo_target_type": settings.get("negativeGeoTargetType", "UNSPECIFIED"),
        }
    return canonical(value), criteria


def execute(ctx, send):
    v = ctx.values
    name = v["campaign_resource_name"]
    account = get_account(ctx, send)["account"]
    campaign(ctx, send, name)
    if set(v["expected_current"]) != set(v["desired"]):
        reject("Expected and desired must specify the same targeting families.")
    expected = canonical(v["expected_current"])
    desired = canonical(v["desired"])
    previous, criteria = snapshot(ctx, send, name, desired)
    if previous != expected:
        conflict("Managed targeting changed; refresh and approve the new diff.")
    operations = []
    changes = []
    mapping = []
    if "location_options" in desired:
        mask = []
        wire = {}
        for field, key in (
            ("positive_geo_target_type", "positiveGeoTargetType"),
            ("negative_geo_target_type", "negativeGeoTargetType"),
        ):
            if previous["location_options"][field] != desired["location_options"][field]:
                mask.append("geo_target_type_setting." + field)
                wire[key] = desired["location_options"][field]
        if mask:
            operations.append(
                update(
                    "campaignOperation", {"resourceName": name, "geoTargetTypeSetting": wire}, mask
                )
            )
            changes.append({"family": "LOCATION_OPTIONS", "action": "UPDATE", "field_mask": mask})
            mapping.append(None)
    if "geo_target_constants" in desired:
        old = set(previous["geo_target_constants"])
        new = set(desired["geo_target_constants"])
        for item in criteria:
            if "location" in item and item["location"]["geoTargetConstant"] in old - new:
                operations.append({"campaignCriterionOperation": {"remove": item["resourceName"]}})
                changes.append(
                    {
                        "family": "GEO",
                        "action": "REMOVE",
                        "resource_name": item["resourceName"],
                        "field_mask": [],
                    }
                )
                mapping.append(None)
        for constant in sorted(new - old):
            operations.append(
                {
                    "campaignCriterionOperation": {
                        "create": {
                            "campaign": name,
                            "negative": False,
                            "location": {"geoTargetConstant": constant},
                        }
                    }
                }
            )
            changes.append({"family": "GEO", "action": "ADD", "field_mask": []})
            mapping.append(len(changes) - 1)
    if "schedule" in desired and desired["schedule"] != previous["schedule"]:
        old = {json.dumps(schedule_wire(i), sort_keys=True) for i in schedule(previous["schedule"])}
        new = {json.dumps(schedule_wire(i), sort_keys=True) for i in schedule(desired["schedule"])}
        for item in criteria:
            if "adSchedule" in item and json.dumps(item["adSchedule"], sort_keys=True) in old - new:
                operations.append({"campaignCriterionOperation": {"remove": item["resourceName"]}})
                changes.append(
                    {
                        "family": "SCHEDULE",
                        "action": "REMOVE",
                        "resource_name": item["resourceName"],
                        "field_mask": [],
                    }
                )
                mapping.append(None)
        for value in sorted(new - old):
            operations.append(
                {
                    "campaignCriterionOperation": {
                        "create": {"campaign": name, "adSchedule": json.loads(value)}
                    }
                }
            )
            changes.append({"family": "SCHEDULE", "action": "ADD", "field_mask": []})
            mapping.append(len(changes) - 1)
    entities, rid = atomic(ctx, send, operations)
    for entity, index in zip(entities, mapping):
        if index is not None:
            changes[index]["resource_name"] = entity["resourceName"]
    current, _ = snapshot(ctx, send, name, desired) if operations else (previous, criteria)
    return {
        **base(ctx),
        "request_id": rid,
        "mutation_operation_count": len(operations),
        "campaign_resource_name": name,
        "previous": previous,
        "current": current,
        "changes": changes,
        "account_time_zone": account["time_zone"],
        "preflight_is_provider_cas": False,
    }
