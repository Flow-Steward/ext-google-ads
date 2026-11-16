"""RSA creation and supported mutable AdService content updates."""

from copy import deepcopy
from .accounts import get_account, call
from .reads import base, resource, literal, AD_FIELDS
from .validation import rsa, rsa_wire
from .mutations_common import group, ad, atomic, complete_rows, unsupported, conflict
from .errors import AdsError

RSA = frozenset({"create_responsive_search_ad", "update_responsive_search_ad"})


def content(entity):
    a = entity["ad"]
    value = a["responsiveSearchAd"]
    result = {"final_urls": a.get("finalUrls", [])}
    for field in ("headlines", "descriptions"):
        result[field] = [
            {
                "text": item["text"],
                **(
                    {"pinned_field": item["pinnedField"]}
                    if item.get("pinnedField") not in {None, "UNSPECIFIED", "UNKNOWN"}
                    else {}
                ),
            }
            for item in value[field]
        ]
    for field in ("path1", "path2"):
        if value.get(field):
            result[field] = value[field]
    return result


def execute(ctx, send):
    get_account(ctx, send)
    v = ctx.values
    if ctx.operation == "create_responsive_search_ad":
        g, c = group(ctx, send, v["ad_group_resource_name"])
        rsa(v["responsive_search_ad"])
        entities, rid = atomic(
            ctx,
            send,
            [
                {
                    "adGroupAdOperation": {
                        "create": {
                            "adGroup": g["resourceName"],
                            "status": "PAUSED",
                            "ad": rsa_wire(v["responsive_search_ad"]),
                        }
                    }
                }
            ],
        )
        name = entities[0]["resourceName"]
        entity, actual_g, actual_c = ad(ctx, send, name)
        if (
            entity["status"] != "PAUSED"
            or actual_g["resourceName"] != g["resourceName"]
            or actual_c["resourceName"] != c["resourceName"]
        ):
            conflict("The created ad association/status could not be confirmed.")
        mask = None
    else:
        name = resource(ctx, v["ad_resource_name"], "ads")
        rows = complete_rows(
            ctx,
            send,
            f"SELECT {AD_FIELDS} FROM ad_group_ad WHERE ad_group_ad.ad.resource_name = {literal(name)} AND ad_group_ad.status != 'REMOVED'",
        )
        if not rows:
            raise AdsError("resource_not_found", "The selected ad is unavailable.")
        if len(rows) != 1:
            unsupported("The ad has multiple associations; select a uniquely scoped Search ad.")
        entity, g, c = ad(ctx, send, rows[0]["adGroupAd"]["resourceName"])
        if entity["ad"]["resourceName"] != name:
            conflict("The selected ad association changed.")
        merged = content(entity)
        merged.update(deepcopy(v["patch"]))
        rsa(merged)
        mask = [
            "final_urls" if key == "final_urls" else "responsive_search_ad." + key
            for key in v["patch"]
        ]
        reply = call(
            ctx,
            send,
            f"customers/{ctx.customer}/ads:mutate",
            {
                "operations": [
                    {
                        "update": {"resourceName": name, **rsa_wire(v["patch"])},
                        "updateMask": ",".join(mask),
                    }
                ],
                "partialFailure": False,
                "validateOnly": False,
                "responseContentType": "MUTABLE_RESOURCE",
            },
            write=True,
        )
        body = reply.body
        values = body.get("results") if isinstance(body, dict) else None
        if (
            not isinstance(values, list)
            or len(values) != 1
            or body.get("partialFailureError")
            or values[0].get("resourceName") != name
            or values[0].get("ad", {}).get("resourceName") != name
        ):
            raise AdsError(
                "outcome_unknown",
                "The ad update result is incomplete; reconcile before retrying.",
                unknown=True,
            )
        rid = reply.request_id
        # Policy is output-only, so fetch actual association after content mutation.
        before_status = entity["status"]
        entity, actual_g, actual_c = ad(ctx, send, entity["resourceName"])
        if (
            actual_g["resourceName"] != g["resourceName"]
            or actual_c["resourceName"] != c["resourceName"]
            or entity["status"] != before_status
        ):
            conflict("The ad association/status changed during content update.")
    policy = entity.get("policySummary", {})
    result = {
        **base(ctx),
        "request_id": rid,
        "mutation_operation_count": 1,
        "ad_resource_name": entity["ad"]["resourceName"],
        "ad_group_ad_resource_name": entity["resourceName"],
        "ad_group_resource_name": g["resourceName"],
        "campaign_resource_name": c["resourceName"],
        "responsive_search_ad": content(entity),
        "status": entity["status"],
        "policy": {
            "review_status": policy.get("reviewStatus"),
            "approval_status": policy.get("approvalStatus"),
        },
    }
    if mask is not None:
        result["update_mask"] = mask
    return result
