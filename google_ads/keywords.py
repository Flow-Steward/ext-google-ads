"""Bounded atomic positive/negative keyword ensures and explicit removals."""

# GAQL uses closed field/source constants and resource literals escaped by reads.literal.

from copy import deepcopy
from .accounts import get_account
from .reads import base, resource, literal, KEYWORD_FIELDS
from .mutations_common import campaign, group, complete_rows, atomic, update, unsupported, conflict
from .validation import keyword_text, currency, reject
from .mutations import strategy
from .errors import AdsError

KEYWORDS = frozenset({"upsert_keywords", "upsert_negative_keywords", "remove_keywords"})
CAMPAIGN_KEYWORD_FIELDS = "campaign.resource_name, campaign_criterion.resource_name, campaign_criterion.campaign, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type, campaign_criterion.status, campaign_criterion.negative, campaign_criterion.type"


def execute(ctx, send):
    account = get_account(ctx, send)["account"]
    if ctx.operation == "remove_keywords":
        return remove(ctx, send)
    v = ctx.values
    positive = ctx.operation == "upsert_keywords"
    if positive:
        currency(account["currency_code"], v["currency_code"])
        parent = v["ad_group_resource_name"]
        g, c = group(ctx, send, parent)
        scope = "AD_GROUP"
    else:
        scope = v["scope"]
        parent = v["parent_resource_name"]
        if scope == "AD_GROUP":
            g, c = group(ctx, send, parent)
        else:
            c = campaign(ctx, send, parent)
            g = None
    entity = "adGroupCriterion" if scope == "AD_GROUP" else "campaignCriterion"
    field = "ad_group_criterion" if scope == "AD_GROUP" else "campaign_criterion"
    kind = entity + "Operation"
    fields = KEYWORD_FIELDS if scope == "AD_GROUP" else CAMPAIGN_KEYWORD_FIELDS
    parent_field = "ad_group" if scope == "AD_GROUP" else "campaign"
    rows = complete_rows(
        ctx,
        send,
        f"SELECT {fields} FROM {field} WHERE {field}.{parent_field} = {literal(parent)} AND {field}.type = 'KEYWORD'",  # nosec B608
    )
    existing = {}
    for row in rows:
        item = row[entity]
        if item.get("status") == "REMOVED" or item.get("negative", False) == positive:
            continue
        if item.get("adGroup" if scope == "AD_GROUP" else "campaign", parent) != parent:
            conflict("The criterion belongs to a different parent.")
        keyword = item.get("keyword")
        if not isinstance(keyword, dict):
            raise AdsError("provider_unavailable", "The keyword snapshot is invalid.")
        identity = (keyword_text(keyword["text"]), keyword["matchType"])
        existing.setdefault(identity, []).append(item)
    normalized = []
    seen = set()
    for item in v["keywords"]:
        item = deepcopy(item)
        item["text"] = keyword_text(item["text"])
        identity = (item["text"], item["match_type"])
        if identity in seen:
            reject("Duplicate keyword identity after trimming outer spaces.")
        seen.add(identity)
        matches = existing.get(identity, [])
        if len(matches) > 1:
            conflict(
                "Multiple current criteria share this keyword identity; resolve in Google Ads."
            )
        old = matches[0] if matches else None
        if positive:
            if "cpc_bid_micros" in item and strategy(c) != "MANUAL_CPC":
                unsupported("Explicit keyword CPC requires Manual CPC.")
            applicable = (
                item.get("cpc_bid_micros")
                or (old or {}).get("cpcBidMicros")
                or g.get("cpcBidMicros")
            )
            if strategy(c) == "MANUAL_CPC" and int(applicable or "0") <= 0:
                reject("Manual CPC requires an applicable group or keyword CPC.")
        normalized.append((item, old))
    operations = []
    pending = []
    items = []
    for index, (item, old) in enumerate(normalized):
        mask = []
        if old is None:
            create = {
                "adGroup" if scope == "AD_GROUP" else "campaign": parent,
                "negative": not positive,
                "keyword": {"text": item["text"], "matchType": item["match_type"]},
            }
            if positive:
                create["status"] = item["status"]
                if "cpc_bid_micros" in item:
                    create["cpcBidMicros"] = item["cpc_bid_micros"]
            operation = {kind: {"create": create}}
            outcome = "CREATED"
        elif positive:
            wire = {"resourceName": old["resourceName"]}
            for source, target in (("status", "status"), ("cpc_bid_micros", "cpcBidMicros")):
                if source in item and item[source] != old.get(target):
                    wire[target] = item[source]
                    mask.append(source)
            operation = update(kind, wire, mask) if mask else None
            outcome = "UPDATED" if mask else "UNCHANGED"
        else:
            operation = None
            outcome = "UNCHANGED"
        result = {
            "input_index": index,
            "criterion_resource_name": old["resourceName"] if old else "",
            "text": item["text"],
            "match_type": item["match_type"],
            "outcome": outcome,
        }
        if positive:
            result.update(status=(old or {}).get("status", item["status"]), update_mask=mask)
            if (old or {}).get("cpcBidMicros") and int(old["cpcBidMicros"]) > 0:
                result["cpc_bid_micros"] = old["cpcBidMicros"]
        items.append(result)
        if operation:
            operations.append(operation)
            pending.append(index)
    entities, rid = atomic(ctx, send, operations)
    for index, actual in zip(pending, entities):
        result = items[index]
        result["criterion_resource_name"] = actual["resourceName"]
        if positive:
            result["status"] = actual["status"]
            if actual.get("cpcBidMicros") and int(actual["cpcBidMicros"]) > 0:
                result["cpc_bid_micros"] = actual["cpcBidMicros"]
    common = {
        **base(ctx),
        "request_id": rid,
        "mutation_operation_count": len(operations),
        "items": items,
    }
    if positive:
        return {
            **common,
            "ad_group_resource_name": parent,
            "campaign_resource_name": c["resourceName"],
            "currency_code": account["currency_code"],
        }
    return {**common, "scope": scope, "parent_resource_name": parent}


def remove(ctx, send):
    names = ctx.values["criterion_resource_names"]
    if len(set(names)) != len(names):
        reject("Criterion resource names must be unique in one removal batch.")
    operations = []
    items = []
    checked = set()
    for index, name in enumerate(names):
        resource(ctx, name)
        ag = "/adGroupCriteria/" in name
        entity = "adGroupCriterion" if ag else "campaignCriterion"
        field = "ad_group_criterion" if ag else "campaign_criterion"
        fields = KEYWORD_FIELDS if ag else CAMPAIGN_KEYWORD_FIELDS
        rows = complete_rows(
            ctx,
            send,
            f"SELECT {fields} FROM {field} WHERE {field}.resource_name = {literal(name)}",  # nosec B608
        )
        if len(rows) != 1 or rows[0].get(entity, {}).get("resourceName") != name:
            raise AdsError("resource_not_found", "The selected keyword criterion is unavailable.")
        item = rows[0][entity]
        if not isinstance(item.get("keyword"), dict):
            unsupported("Only explicitly selected keyword criteria may be removed.")
        parent = (
            item.get("adGroup")
            if ag
            else item.get("campaign", rows[0].get("campaign", {}).get("resourceName"))
        )
        if parent not in checked:
            if ag:
                group(ctx, send, parent)
            else:
                campaign(ctx, send, parent)
            checked.add(parent)
        removed = item.get("status") == "REMOVED"
        items.append(
            {
                "input_index": index,
                "criterion_resource_name": name,
                "polarity": "NEGATIVE" if item.get("negative", False) else "POSITIVE",
                "outcome": "ALREADY_REMOVED" if removed else "REMOVED",
                "status": "REMOVED",
            }
        )
        if not removed:
            operations.append({entity + "Operation": {"remove": name}})
    _, rid = atomic(ctx, send, operations)
    return {
        **base(ctx),
        "request_id": rid,
        "mutation_operation_count": len(operations),
        "items": items,
    }
