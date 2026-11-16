"""Shared bounded atomic writes and fresh Search ancestry checks."""

import json
from .accounts import call
from .errors import AdsError
from .reads import search, resource, verify_refs, campaign_row, group_row, literal, AD_FIELDS
from .projections import campaign_summary
from .search_create import RESULT_KEYS, MAX_MUTATE_OPERATIONS, MAX_MUTATE_BYTES, MAX_RESULT_BYTES


def unsupported(message):
    raise AdsError("unsupported_configuration", message)


def conflict(message):
    raise AdsError("state_conflict", message)


def active(entity):
    if entity.get("status") not in {"ENABLED", "PAUSED"}:
        unsupported("The selected resource is removed or has an unsupported status.")
    return entity


def campaign(ctx, send, name):
    row = campaign_row(ctx, send, name)
    active(row["campaign"])
    if not campaign_summary(row)["supported_for_writes"]:
        unsupported("Writes require a Search campaign with a supported standard bidding strategy.")
    return row["campaign"]


def group(ctx, send, name):
    row = group_row(ctx, send, name)
    entity = active(row["adGroup"])
    if entity.get("type") != "SEARCH_STANDARD":
        unsupported("Writes require a standard Search ad group.")
    parent = entity.get("campaign", row.get("campaign", {}).get("resourceName"))
    return entity, campaign(ctx, send, parent)


def ad(ctx, send, name):
    resource(ctx, name, "adGroupAds")
    rows, cursor = search(
        ctx,
        send,
        f"SELECT {AD_FIELDS} FROM ad_group_ad WHERE ad_group_ad.resource_name = {literal(name)}",
    )
    if cursor or len(rows) != 1 or rows[0].get("adGroupAd", {}).get("resourceName") != name:
        raise AdsError("resource_not_found", "The selected ad is unavailable.")
    row = rows[0]
    verify_refs(ctx, row)
    entity = active(row["adGroupAd"])
    if entity.get("ad", {}).get("type") != "RESPONSIVE_SEARCH_AD":
        unsupported("Writes require a responsive Search ad.")
    parent = entity.get("adGroup", row.get("adGroup", {}).get("resourceName"))
    g, c = group(ctx, send, parent)
    if row.get("campaign", {}).get("resourceName") != c["resourceName"]:
        conflict("The ad ancestry changed; refresh the selected resources.")
    return entity, g, c


def complete_rows(ctx, send, query):
    # Mutations must inspect a complete bounded snapshot, never a silently truncated one.
    rows, cursor = search(ctx, send, query)
    if cursor:
        unsupported("The preflight snapshot exceeds one bounded provider page.")
    verify_refs(ctx, rows)
    return rows


def atomic(ctx, send, operations):
    if not operations:
        return [], None
    if (
        len(operations) > MAX_MUTATE_OPERATIONS
        or len(json.dumps(operations, ensure_ascii=False).encode()) > MAX_MUTATE_BYTES
        or len(operations) * 448 + 2048 > MAX_RESULT_BYTES
    ):
        raise AdsError(
            "validation_failed", "The complete atomic request/result exceeds its bounded capacity."
        )
    reply = call(
        ctx,
        send,
        f"customers/{ctx.customer}/googleAds:mutate",
        {
            "mutateOperations": operations,
            "partialFailure": False,
            "validateOnly": False,
            "responseContentType": "MUTABLE_RESOURCE",
        },
        write=True,
    )
    body = reply.body
    values = body.get("mutateOperationResponses") if isinstance(body, dict) else None
    if (
        not isinstance(values, list)
        or len(values) != len(operations)
        or body.get("partialFailureError")
    ):
        raise AdsError(
            "outcome_unknown",
            "The atomic result is incomplete; reconcile before retrying.",
            unknown=True,
        )
    entities = []
    for operation, value in zip(operations, values):
        kind = next(iter(operation))
        result_key, entity_key, _, _ = RESULT_KEYS[kind]
        result = value.get(result_key) if isinstance(value, dict) else None
        if not isinstance(result, dict):
            raise AdsError("outcome_unknown", "The atomic result type is incomplete.", unknown=True)
        name = result.get("resourceName")
        collection = {
            "campaignOperation": "campaigns",
            "campaignBudgetOperation": "campaignBudgets",
            "adGroupOperation": "adGroups",
            "adGroupAdOperation": "adGroupAds",
            "adGroupCriterionOperation": "adGroupCriteria",
            "campaignCriterionOperation": "campaignCriteria",
        }[kind]
        resource(ctx, name, collection)
        requested = operation[kind]
        expected = requested.get("remove") or requested.get("update", {}).get("resourceName")
        if expected and name != expected:
            raise AdsError(
                "outcome_unknown",
                "The provider returned a different resource mapping.",
                unknown=True,
            )
        entity = result.get(entity_key)
        if "remove" not in requested and (
            not isinstance(entity, dict) or entity.get("resourceName") != name
        ):
            raise AdsError(
                "outcome_unknown", "Mutable resource confirmation is missing.", unknown=True
            )
        verify_refs(ctx, entity)
        entities.append(entity if entity is not None else {"resourceName": name})
    return entities, reply.request_id


def update(kind, value, mask):
    return {kind: {"update": value, "updateMask": ",".join(mask)}}
