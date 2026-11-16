"""Explicit campaign, budget, bidding, group and delivery operations."""

# GAQL uses closed field/source constants and resource literals escaped by reads.literal.

from copy import deepcopy
from .accounts import get_account
from .reads import base, literal, resource, GROUP_FIELDS, KEYWORD_FIELDS, campaign_row
from .validation import currency, dates, reject, bidding_wire
from .projections import campaign_detail
from .mutations_common import (
    campaign,
    group,
    ad,
    atomic,
    update,
    complete_rows,
    unsupported,
    conflict,
)

MUTATIONS = frozenset(
    {
        "update_campaign",
        "update_campaign_budget",
        "update_bidding",
        "create_ad_group",
        "update_ad_group",
        "set_delivery_status",
    }
)


def strategy(c):
    return (
        "MAXIMIZE_CLICKS"
        if c["biddingStrategyType"] == "TARGET_SPEND"
        else c["biddingStrategyType"]
    )


def manual_compatible(ctx, send, c):
    condition = "campaign.resource_name = " + literal(c["resourceName"])
    groups = complete_rows(
        ctx,
        send,
        f"SELECT {GROUP_FIELDS} FROM ad_group WHERE {condition} AND ad_group.status != 'REMOVED'",  # nosec B608
    )
    keywords = complete_rows(
        ctx,
        send,
        f"SELECT {KEYWORD_FIELDS} FROM ad_group_criterion WHERE {condition} AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != 'REMOVED'",  # nosec B608
    )
    defaults = {r["adGroup"]["resourceName"]: r["adGroup"].get("cpcBidMicros") for r in groups}
    for row in keywords:
        k = row["adGroupCriterion"]
        if int(k.get("cpcBidMicros") or defaults.get(k["adGroup"]) or "0") <= 0:
            unsupported("Set compatible group or keyword CPCs before selecting Manual CPC.")


def execute(ctx, send):
    v = ctx.values
    account = get_account(ctx, send)["account"]
    if "currency_code" in v:
        currency(account["currency_code"], v["currency_code"])
    op = ctx.operation
    if op == "set_delivery_status":
        return delivery(ctx, send)
    if op == "update_ad_group":
        g, c = group(ctx, send, v["ad_group_resource_name"])
    else:
        c = campaign(ctx, send, v["campaign_resource_name"])
    common = base(ctx)
    campaign_name = c["resourceName"]
    operations = []
    if op == "update_campaign":
        patch = v["patch"]
        if "name" in patch and not patch["name"].strip():
            reject("Campaign name must not be blank.")
        dates(
            patch,
            account["time_zone"],
            existing={
                "start_date_time": c.get("startDateTime"),
                "end_date_time": c.get("endDateTime"),
            },
        )
        wire = {"resourceName": campaign_name}
        mask = []
        fields = {
            "name": "name",
            "start_date_time": "startDateTime",
            "end_date_time": "endDateTime",
        }
        for k, value in patch.items():
            if k == "network_settings":
                wire["networkSettings"] = {
                    "targetGoogleSearch": value["target_google_search"],
                    "targetSearchNetwork": value["target_search_network"],
                    "targetContentNetwork": value["target_content_network"],
                }
                mask.extend("network_settings." + f for f in value)
            else:
                wire[fields[k]] = value
                mask.append(k)
        operations = [update("campaignOperation", wire, mask)]
        entities, rid = atomic(ctx, send, operations)
        actual = entities[0]
        applied = deepcopy(patch)
        for k in fields:
            if k in applied:
                applied[k] = actual[fields[k]]
        if "network_settings" in applied:
            # Optional mutable fields are not a complete account-state snapshot.
            actual_network = campaign_row(ctx, send, campaign_name)["campaign"].get(
                "networkSettings", {}
            )
            applied["network_settings"] = {
                k: actual_network.get(
                    {
                        "target_google_search": "targetGoogleSearch",
                        "target_search_network": "targetSearchNetwork",
                        "target_content_network": "targetContentNetwork",
                    }[k],
                    False,
                )
                for k in applied["network_settings"]
            }
        result = {
            "campaign_resource_name": campaign_name,
            "applied_patch": applied,
            "update_mask": mask,
            "status": actual["status"],
        }
    elif op == "update_campaign_budget":
        name = resource(ctx, c.get("campaignBudget"), "campaignBudgets")
        rows = complete_rows(
            ctx,
            send,
            f"SELECT campaign_budget.resource_name, campaign_budget.amount_micros, campaign_budget.explicitly_shared, campaign_budget.period FROM campaign_budget WHERE campaign_budget.resource_name = {literal(name)}",  # nosec B608
        )
        if len(rows) != 1 or rows[0].get("campaignBudget", {}).get("resourceName") != name:
            conflict("The campaign budget changed or is unavailable.")
        b = rows[0]["campaignBudget"]
        users = complete_rows(
            ctx,
            send,
            f"SELECT campaign.resource_name FROM campaign WHERE campaign.campaign_budget = {literal(name)} AND campaign.status != 'REMOVED'",  # nosec B608
        )
        names = sorted(r["campaign"]["resourceName"] for r in users)
        if (
            b.get("explicitlyShared", False) is not False
            or b.get("period") != "DAILY"
            or names != [campaign_name]
        ):
            unsupported("Only an unshared DAILY budget used by this campaign is supported.")
        previous = b["amountMicros"]
        if previous != v["expected_current_amount_micros"]:
            conflict(
                "The observed budget differs from the expected amount; refresh before updating."
            )
        mask = ["amount_micros"]
        if v["amount_micros"] != previous:
            operations = [
                update(
                    "campaignBudgetOperation",
                    {"resourceName": name, "amountMicros": v["amount_micros"]},
                    mask,
                )
            ]
        entities, rid = atomic(ctx, send, operations)
        actual = entities[0] if entities else b
        result = {
            "campaign_resource_name": campaign_name,
            "budget_resource_name": name,
            "previous_amount_micros": previous,
            "amount_micros": actual["amountMicros"],
            "currency_code": account["currency_code"],
            "explicitly_shared": actual.get("explicitlyShared", False),
            "period": b["period"],
            "affected_campaign_resource_names": names,
            "update_mask": mask,
        }
    elif op == "update_bidding":
        previous = strategy(c)
        if previous != v["expected_current_strategy"]:
            conflict("The campaign bidding strategy changed; refresh before updating.")
        desired = v["bidding"]
        if desired["strategy"] == "MANUAL_CPC":
            manual_compatible(ctx, send, c)
            wire = {"manualCpc": {"enhancedCpcEnabled": False}}
            mask = ["manual_cpc.enhanced_cpc_enabled"]
        else:
            wire = bidding_wire(desired)
            mask = (
                ["target_spend.cpc_bid_ceiling_micros"]
                if desired["strategy"] == "MAXIMIZE_CLICKS"
                else ["maximize_conversions.target_cpa_micros"]
            )
        operations = [update("campaignOperation", {"resourceName": campaign_name, **wire}, mask)]
        entities, rid = atomic(ctx, send, operations)
        b = campaign_detail(campaign_row(ctx, send, campaign_name))["bidding"]
        public = {"strategy": b["strategy_type"]}
        for key in ("cpc_bid_ceiling_micros", "target_cpa_micros"):
            if b[key] is not None and int(b[key]) > 0:
                public[key] = b[key]
        result = {
            "campaign_resource_name": campaign_name,
            "previous_strategy": previous,
            "bidding": public,
            "currency_code": account["currency_code"],
            "update_mask": mask,
        }
    else:
        patch = v if op == "create_ad_group" else v["patch"]
        if "name" in patch and not patch["name"].strip():
            reject("Ad group name must not be blank.")
        if "cpc_bid_micros" in patch and strategy(c) != "MANUAL_CPC":
            unsupported("Explicit ad group CPC requires Manual CPC.")
        if op == "create_ad_group":
            if strategy(c) == "MANUAL_CPC" and "cpc_bid_micros" not in patch:
                reject("A new Manual CPC ad group requires its default CPC.")
            wire = {
                "campaign": campaign_name,
                "name": v["name"],
                "status": "PAUSED",
                "type": "SEARCH_STANDARD",
            }
            if "cpc_bid_micros" in v:
                wire["cpcBidMicros"] = v["cpc_bid_micros"]
            operations = [{"adGroupOperation": {"create": wire}}]
            mask = []
        else:
            wire = {"resourceName": g["resourceName"]}
            mask = list(patch)
            for k, value in patch.items():
                wire[{"name": "name", "cpc_bid_micros": "cpcBidMicros"}[k]] = value
            operations = [update("adGroupOperation", wire, mask)]
        entities, rid = atomic(ctx, send, operations)
        actual = entities[0]
        if op == "create_ad_group" and actual.get("status") != "PAUSED":
            conflict("The provider did not confirm a PAUSED new ad group.")
        result = {
            "ad_group_resource_name": actual["resourceName"],
            "campaign_resource_name": campaign_name,
            "name": actual["name"],
            "status": actual["status"],
            "cpc_bid_micros": actual.get("cpcBidMicros"),
            "currency_code": account["currency_code"],
        }
        if op == "update_ad_group":
            result["update_mask"] = mask
    return {**common, "request_id": rid, "mutation_operation_count": len(operations), **result}


def delivery(ctx, send):
    v = ctx.values
    kind = v["resource_type"]
    name = v["resource_name"]
    if kind == "CAMPAIGN":
        entity = c = campaign(ctx, send, name)
        operation = "campaignOperation"
        g = None
    elif kind == "AD_GROUP":
        entity, c = group(ctx, send, name)
        g = entity
        operation = "adGroupOperation"
    else:
        entity, g, c = ad(ctx, send, name)
        operation = "adGroupAdOperation"
    previous = entity["status"]
    operations = (
        []
        if previous == v["status"]
        else [update(operation, {"resourceName": name, "status": v["status"]}, ["status"])]
    )
    entities, rid = atomic(ctx, send, operations)
    actual = entities[0] if entities else entity
    notes = []
    policy = entity.get("policySummary", {}).get("reviewStatus") == "REVIEW_IN_PROGRESS"
    if kind == "AD_GROUP_AD" and c["status"] == "PAUSED" and g["status"] == "PAUSED" and policy:
        notes.append("Campaign and ad group remain PAUSED; policy review is in progress.")
    else:
        if kind != "CAMPAIGN" and c["status"] == "PAUSED":
            notes.append("The parent campaign remains PAUSED.")
        if kind == "AD_GROUP_AD" and g["status"] == "PAUSED":
            notes.append("The parent ad group remains PAUSED.")
        if policy:
            notes.append("Policy review is in progress.")
    return {
        **base(ctx),
        "request_id": rid,
        "mutation_operation_count": len(operations),
        "resource_type": kind,
        "resource_name": name,
        "previous_status": previous,
        "status": actual["status"],
        "update_mask": ["status"],
        "serving_guaranteed": False,
        "delivery_notes": notes,
    }
