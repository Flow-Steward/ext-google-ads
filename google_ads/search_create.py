"""One atomic expanded Search mutate; validate-only shares the exact plan."""

from __future__ import annotations
import json
from .accounts import call, get_account, API_VERSION
from .errors import AdsError
from .validation import specification, bidding_wire, rsa_wire, schedule, schedule_wire

MAX_MUTATE_OPERATIONS = 10000
MAX_MUTATE_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 9 * 512 * 1024
RESULT_KEYS = {
    "campaignBudgetOperation": (
        "campaignBudgetResult",
        "campaignBudget",
        "budget",
        "NOT_APPLICABLE",
    ),
    "campaignOperation": ("campaignResult", "campaign", "campaign", "PAUSED"),
    "adGroupOperation": ("adGroupResult", "adGroup", "ad_group", "PAUSED"),
    "adGroupAdOperation": ("adGroupAdResult", "adGroupAd", "ad", "PAUSED"),
    "adGroupCriterionOperation": (
        "adGroupCriterionResult",
        "adGroupCriterion",
        "keyword",
        "ENABLED",
    ),
    "campaignCriterionOperation": (
        "campaignCriterionResult",
        "campaignCriterion",
        "criterion",
        "NOT_APPLICABLE",
    ),
}


def plan(ctx, spec):
    root = f"customers/{ctx.customer}"
    budget = f"{root}/campaignBudgets/-1"
    campaign = f"{root}/campaigns/-2"
    operations = []
    keys = []

    def add(kind, key, create):
        operations.append({kind: {"create": create}})
        keys.append(key)

    add(
        "campaignBudgetOperation",
        "budget",
        {
            "resourceName": budget,
            "name": (spec["name"] + " budget")[:255],
            "amountMicros": spec["average_daily_budget_micros"],
            "period": "DAILY",
            "deliveryMethod": "STANDARD",
            "explicitlyShared": False,
        },
    )
    target = spec["targeting"]
    network = spec["network_settings"]
    c = {
        "resourceName": campaign,
        "name": spec["name"],
        "status": "PAUSED",
        "advertisingChannelType": "SEARCH",
        "campaignBudget": budget,
        "containsEuPoliticalAdvertising": spec["contains_eu_political_advertising"],
        "networkSettings": {
            "targetGoogleSearch": network["target_google_search"],
            "targetSearchNetwork": network["target_search_network"],
            "targetContentNetwork": False,
        },
        "geoTargetTypeSetting": {
            "positiveGeoTargetType": target["location_options"]["positive_geo_target_type"],
            "negativeGeoTargetType": target["location_options"]["negative_geo_target_type"],
        },
        **bidding_wire(spec["bidding"]),
    }
    for source, destination in (
        ("start_date_time", "startDateTime"),
        ("end_date_time", "endDateTime"),
    ):
        if source in spec:
            c[destination] = spec[source]
    add("campaignOperation", "campaign", c)
    for index, group in enumerate(spec["ad_groups"]):
        group_name = f"{root}/adGroups/{-3 - index}"
        g = {
            "resourceName": group_name,
            "campaign": campaign,
            "name": group["name"],
            "type": "SEARCH_STANDARD",
            "status": "PAUSED",
        }
        if "cpc_bid_micros" in group:
            g["cpcBidMicros"] = group["cpc_bid_micros"]
        add("adGroupOperation", group["key"], g)
        for ad in group["ads"]:
            add(
                "adGroupAdOperation",
                ad["key"],
                {"adGroup": group_name, "status": "PAUSED", "ad": rsa_wire(ad["content"])},
            )
        for keyword in group["keywords"]:
            k = {
                "adGroup": group_name,
                "status": "ENABLED",
                "keyword": {"text": keyword["text"], "matchType": keyword["match_type"]},
            }
            if "cpc_bid_micros" in keyword:
                k["cpcBidMicros"] = keyword["cpc_bid_micros"]
            add("adGroupCriterionOperation", keyword["key"], k)
    for constant in target["geo_target_constants"]:
        add(
            "campaignCriterionOperation",
            "geo_" + constant.split("/")[-1],
            {"campaign": campaign, "location": {"geoTargetConstant": constant}, "negative": False},
        )
    for index, interval in enumerate(schedule(target["schedule"])):
        add(
            "campaignCriterionOperation",
            f"geo_schedule_{index}",
            {"campaign": campaign, "adSchedule": schedule_wire(interval)},
        )
    if len(operations) > MAX_MUTATE_OPERATIONS:
        raise AdsError(
            "validation_failed", "The expanded request exceeds10000 atomic mutate operations."
        )
    # A conservative full-result capacity estimate before any write is dispatched.
    estimate = sum(len(key.encode()) + 384 for key in keys) + 2048
    if (
        estimate > MAX_RESULT_BYTES
        or len(json.dumps(operations, ensure_ascii=False, separators=(",", ":")).encode())
        > MAX_MUTATE_BYTES
    ):
        raise AdsError(
            "validation_failed",
            "The expanded request or complete result exceeds the safe byte budget.",
        )
    return operations, keys


def execute(ctx, send):
    account = get_account(ctx, send)["account"]
    spec = specification(ctx.values["specification"], account)
    operations, keys = plan(ctx, spec)
    validate_only = ctx.operation == "validate_search_campaign"
    reply = call(
        ctx,
        send,
        f"customers/{ctx.customer}/googleAds:mutate",
        {
            "mutateOperations": operations,
            "partialFailure": False,
            "validateOnly": validate_only,
            "responseContentType": "MUTABLE_RESOURCE",
        },
        write=not validate_only,
    )
    common = {
        "customer_id": ctx.customer,
        "connection_id": ctx.connection_id,
        "api_version": API_VERSION,
    }
    if validate_only:
        return {
            **common,
            "valid": True,
            "expanded_operation_count": len(operations),
            "warnings": [],
            "request_id": reply.request_id,
        }
    body = reply.body
    responses = body.get("mutateOperationResponses") if isinstance(body, dict) else None
    if (
        not isinstance(responses, list)
        or len(responses) != len(operations)
        or body.get("partialFailureError")
    ):
        raise AdsError(
            "outcome_unknown",
            "The atomic write response is incomplete; reconcile before retrying.",
            unknown=True,
        )
    mapping = []
    names = set()
    for operation, key, response in zip(operations, keys, responses):
        operation_key = next(iter(operation))
        result_key, entity, kind, status = RESULT_KEYS[operation_key]
        result = response.get(result_key, {}) if isinstance(response, dict) else {}
        resource_name = result.get("resourceName", "")
        if (
            not isinstance(resource_name, str)
            or not resource_name.startswith(f"customers/{ctx.customer}/")
            or "/-" in resource_name
            or resource_name in names
        ):
            raise AdsError(
                "outcome_unknown",
                "The created resource mapping is incomplete; reconcile before retrying.",
                unknown=True,
            )
        names.add(resource_name)
        if status != "NOT_APPLICABLE" and result.get(entity, {}).get("status") != status:
            raise AdsError(
                "outcome_unknown",
                "The provider did not confirm the requested safe resource status.",
                unknown=True,
            )
        mapping.append(
            {"local_key": key, "kind": kind, "resource_name": resource_name, "status": status}
        )
    return {
        **common,
        "currency_code": account["currency_code"],
        "campaign_resource_name": mapping[1]["resource_name"],
        "status": "PAUSED",
        "explicitly_shared": False,
        "resource_mapping": mapping,
        "expanded_operation_count": len(operations),
        "request_id": reply.request_id,
    }
