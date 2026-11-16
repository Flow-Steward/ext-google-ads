"""Allowlisted ordinary read actions and Google REST-to-contract projections."""

# GAQL uses closed field/source constants and resource literals escaped by reads.literal.

from __future__ import annotations
from dataclasses import replace
import re
import time
from .accounts import API_VERSION, call, get_account
from .errors import AdsError
from .paging import decode, digest, encode, window
from .projections import (
    campaign_summary,
    networks,
    campaign_detail,
    group_summary,
    ad_summary,
    keyword_summary,
    targeting_summary,
)

READS = frozenset(
    {
        "list_accessible_accounts",
        "list_manager_clients",
        "list_campaigns",
        "get_campaign",
        "list_ad_groups",
        "list_ads",
        "list_keywords",
        "list_targeting",
    }
)
CAMPAIGN_FIELDS = "campaign.id, campaign.resource_name, campaign.name, campaign.status, campaign.advertising_channel_type, campaign.campaign_budget, campaign.start_date_time, campaign.end_date_time, campaign.network_settings.target_google_search, campaign.network_settings.target_search_network, campaign.network_settings.target_content_network, campaign.network_settings.target_partner_search_network, campaign.bidding_strategy, campaign.bidding_strategy_type, campaign.target_spend.cpc_bid_ceiling_micros, campaign.maximize_conversions.target_cpa_micros, campaign.serving_status, campaign.primary_status, campaign.primary_status_reasons, campaign.contains_eu_political_advertising, campaign.geo_target_type_setting.positive_geo_target_type, campaign.geo_target_type_setting.negative_geo_target_type, campaign_budget.resource_name, campaign_budget.amount_micros, campaign_budget.explicitly_shared"
GROUP_FIELDS = "campaign.resource_name, ad_group.resource_name, ad_group.campaign, ad_group.name, ad_group.status, ad_group.type, ad_group.cpc_bid_micros"
AD_FIELDS = "campaign.resource_name, ad_group.resource_name, ad_group_ad.resource_name, ad_group_ad.ad_group, ad_group_ad.status, ad_group_ad.ad.resource_name, ad_group_ad.ad.type, ad_group_ad.ad.final_urls, ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions, ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2, ad_group_ad.policy_summary.approval_status, ad_group_ad.policy_summary.review_status, ad_group_ad.policy_summary.policy_topic_entries"
KEYWORD_FIELDS = "campaign.resource_name, ad_group_criterion.resource_name, ad_group_criterion.ad_group, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.status, ad_group_criterion.negative, ad_group_criterion.cpc_bid_micros"
CRITERION_FIELDS = "campaign_criterion.resource_name, campaign_criterion.type, campaign_criterion.negative, campaign_criterion.status, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant, campaign_criterion.ad_schedule.day_of_week, campaign_criterion.ad_schedule.start_hour, campaign_criterion.ad_schedule.start_minute, campaign_criterion.ad_schedule.end_hour, campaign_criterion.ad_schedule.end_minute"


def literal(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def resource(ctx, value, kind=None):
    if not isinstance(value, str) or not value.startswith(f"customers/{ctx.customer}/"):
        raise AdsError(
            "resource_account_mismatch", "The resource belongs to another advertising customer."
        )
    if kind and not re.fullmatch(r"customers/[0-9]{10}/" + kind + r"/[0-9]+(?:~[0-9]+)?", value):
        raise AdsError("invalid_payload", "The resource has an invalid type or identifier.")
    return value


def verify_refs(ctx, value):
    # Check typed Google resource fields, never free text such as names or search terms.
    resource_fields = {"resourceName", "campaign", "adGroup", "campaignBudget", "biddingStrategy"}
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in resource_fields and isinstance(nested, str) and nested:
                resource(ctx, nested)
            elif isinstance(nested, (dict, list)):
                verify_refs(ctx, nested)
    elif isinstance(value, list):
        for nested in value:
            verify_refs(ctx, nested)


def base(ctx):
    return {
        "customer_id": ctx.customer,
        "connection_id": ctx.connection_id,
        "api_version": API_VERSION,
    }


def search(ctx, send, query, provider_cursor="", customer=None):
    body = {"query": query}
    if provider_cursor:
        body["pageToken"] = provider_cursor
    reply = call(ctx, send, f"customers/{customer or ctx.customer}/googleAds:search", body)
    if not isinstance(reply.body, dict) or not isinstance(reply.body.get("results", []), list):
        raise AdsError("provider_unavailable", "Invalid provider search response.")
    rows = reply.body.get("results", [])
    if len(rows) > 10000 or any(not isinstance(row, dict) for row in rows):
        raise AdsError("provider_unavailable", "Invalid provider search rows.")
    return rows, reply.body.get("nextPageToken") or ""


def paged(ctx, send, queries, project):
    binding = digest(queries)
    state = decode(ctx, binding)
    index = state.get("index", 0)
    provider_cursor = state.get("page", "")
    offset = state.get("offset", 0)
    expected = state.get("fingerprint")
    selected = []
    size = ctx.values.get("page_size", 100)
    while index < len(queries):
        rows, next_page = search(ctx, send, queries[index], provider_cursor)
        fingerprint = digest(rows)
        if expected and fingerprint != expected:
            raise AdsError(
                "state_conflict", "The provider page changed; restart the read.", restart=True
            )
        if offset > len(rows):
            raise AdsError(
                "state_conflict", "The provider page no longer contains this offset.", restart=True
            )
        take = min(size - len(selected), len(rows) - offset)
        for row in rows[offset : offset + take]:
            verify_refs(ctx, row)
            selected.append(project(row))
        offset += take
        if offset < len(rows):
            cursor = encode(
                ctx,
                binding,
                {
                    "index": index,
                    "page": provider_cursor,
                    "offset": offset,
                    "fingerprint": fingerprint,
                },
            )
            return selected, cursor, False
        if next_page:
            if next_page == provider_cursor:
                raise AdsError("provider_unavailable", "The provider repeated its page cursor.")
            provider_cursor = next_page
        else:
            index += 1
            provider_cursor = ""
        offset = 0
        expected = None
        if len(selected) >= size and index < len(queries):
            return (
                selected,
                encode(ctx, binding, {"index": index, "page": provider_cursor, "offset": 0}),
                False,
            )
    return selected, None, False


def campaign_row(ctx, send, name):
    resource(ctx, name, "campaigns")
    rows, _ = search(
        ctx,
        send,
        f"SELECT {CAMPAIGN_FIELDS} FROM campaign WHERE campaign.resource_name = {literal(name)}",  # nosec B608
    )
    if len(rows) != 1 or rows[0].get("campaign", {}).get("resourceName") != name:
        raise AdsError("resource_not_found", "The selected campaign is unavailable.")
    verify_refs(ctx, rows[0])
    return rows[0]


def group_row(ctx, send, name):
    resource(ctx, name, "adGroups")
    rows, _ = search(
        ctx,
        send,
        f"SELECT {GROUP_FIELDS} FROM ad_group WHERE ad_group.resource_name = {literal(name)}",  # nosec B608
    )
    if len(rows) != 1 or rows[0].get("adGroup", {}).get("resourceName") != name:
        raise AdsError("resource_not_found", "The selected ad group is unavailable.")
    verify_refs(ctx, rows[0])
    return rows[0]


def accessible(ctx, send):
    binding = "direct-accessible-customers"
    decode(ctx, binding)
    direct = replace(ctx, manager="")
    reply = call(direct, send, "customers:listAccessibleCustomers")
    if not isinstance(reply.body, dict) or not isinstance(
        reply.body.get("resourceNames", []), list
    ):
        raise AdsError("provider_unavailable", "Invalid account discovery response.")
    names = reply.body.get("resourceNames", [])
    if len(names) > 10000:
        names = names[:10000]
    selected, cursor, truncated = window(
        ctx, binding, names, incomplete=len(reply.body.get("resourceNames", [])) > 10000
    )
    items = []
    for name in selected:
        if not isinstance(name, str) or not re.fullmatch(r"customers/[0-9]{10}", name):
            raise AdsError("provider_unavailable", "Invalid discovered customer ID.")
        customer = name.split("/")[-1]
        item = {
            "customer_id": customer,
            "resource_name": name,
            "descriptive_name": None,
            "manager": None,
            "test_account": None,
            "currency_code": None,
            "time_zone": None,
            "metadata_error": None,
        }
        try:
            metadata = get_account(replace(direct, customer=customer), send, allow_manager=True)[
                "account"
            ]
            for key in (
                "descriptive_name",
                "manager",
                "test_account",
                "currency_code",
                "time_zone",
            ):
                item[key] = metadata[key]
        except AdsError as e:
            item["metadata_error"] = {"code": e.code, "message": e.message}
        items.append(item)
    return {
        "connection_id": ctx.connection_id,
        "api_version": API_VERSION,
        "items": items,
        "next_cursor": cursor,
        "truncated": truncated,
    }


def manager_clients(ctx, send):
    manager = ctx.values["manager_id"]
    binding = "manager-clients:" + manager
    decode(ctx, binding)
    queue = [(manager, [manager])]
    expanded = set()
    items = []
    incomplete = False
    while queue:
        current, path = queue.pop(0)
        if current in expanded:
            continue
        expanded.add(current)
        route = replace(ctx, customer=current, manager=manager)
        query = "SELECT customer_client.id, customer_client.client_customer, customer_client.manager, customer_client.test_account, customer_client.descriptive_name, customer_client.level FROM customer_client WHERE customer_client.level = 1"
        try:
            rows, next_page = search(route, send, query)
        except AdsError as e:
            if len(path) == 1:
                raise
            for item in items:
                if item["access_path"] == path:
                    item["branch_status"] = "deadline" if e.code == "timeout" else "inaccessible"
                    item["branch_error"] = {"code": e.code, "message": e.message}
            incomplete = True
            continue
        if next_page:
            incomplete = True
        for row in rows:
            c = row.get("customerClient", {})
            cid = str(c.get("id") or str(c.get("clientCustomer", "")).split("/")[-1])
            if not re.fullmatch(r"[0-9]{10}", cid):
                raise AdsError("provider_unavailable", "Invalid manager discovery row.")
            cycle = cid in path
            depth = len(path)
            status = (
                "cycle_detected"
                if cycle
                else "depth_limit"
                if depth >= 20 and c.get("manager", False)
                else "accessible"
            )
            if status != "accessible":
                incomplete = True
            item = {
                "customer_id": cid,
                "manager": c.get("manager", False),
                "test_account": c.get("testAccount", False),
                "descriptive_name": c.get("descriptiveName"),
                "access_path": [*path, cid],
                "depth": depth,
                "branch_status": status,
                "branch_error": None,
            }
            items.append(item)
            if c.get("manager", False) and status == "accessible":
                queue.append((cid, [*path, cid]))
            if len(items) >= 10000:
                items[-1]["branch_status"] = "node_limit"
                incomplete = True
                queue = []
                break
        if time.monotonic() >= ctx.deadline:
            incomplete = True
            break
    selected, cursor, truncated = window(ctx, binding, items, incomplete=incomplete)
    return {
        "connection_id": ctx.connection_id,
        "api_version": API_VERSION,
        "manager_id": manager,
        "items": selected,
        "next_cursor": cursor,
        "truncated": truncated,
    }


def handle_read(ctx, send):
    if ctx.operation == "list_accessible_accounts":
        return accessible(ctx, send)
    if ctx.operation == "list_manager_clients":
        return manager_clients(ctx, send)
    v = ctx.values
    for key, kind in (("campaign", "campaigns"), ("ad_group", "adGroups")):
        if key in v:
            resource(ctx, v[key], kind)
    account = get_account(ctx, send)["account"]
    common = base(ctx)
    if ctx.operation == "get_campaign":
        return {
            **common,
            "currency_code": account["currency_code"],
            "time_zone": account["time_zone"],
            "campaign": campaign_detail(campaign_row(ctx, send, v["campaign"])),
        }
    extras = {}
    if ctx.operation == "list_campaigns":
        filters = []
        for key, field in (
            ("statuses", "campaign.status"),
            ("advertising_channel_types", "campaign.advertising_channel_type"),
        ):
            if key in v:
                filters.append(field + " IN (" + ", ".join(literal(x) for x in v[key]) + ")")
        where = " WHERE " + " AND ".join(filters) if filters else ""
        queries = [f"SELECT {CAMPAIGN_FIELDS} FROM campaign{where} ORDER BY campaign.id"]  # nosec B608
        project = campaign_summary
    elif ctx.operation == "list_ad_groups":
        campaign_row(ctx, send, v["campaign"])
        queries = [
            f"SELECT {GROUP_FIELDS} FROM ad_group WHERE campaign.resource_name = {literal(v['campaign'])} ORDER BY ad_group.id"  # nosec B608
        ]
        project = group_summary
        extras["currency_code"] = account["currency_code"]
    elif ctx.operation in {"list_ads", "list_keywords"}:
        if "campaign" in v:
            campaign_row(ctx, send, v["campaign"])
            condition = "campaign.resource_name = " + literal(v["campaign"])
        else:
            group_row(ctx, send, v["ad_group"])
            condition = "ad_group.resource_name = " + literal(v["ad_group"])
        if ctx.operation == "list_ads":
            queries = [
                f"SELECT {AD_FIELDS} FROM ad_group_ad WHERE {condition} ORDER BY ad_group_ad.ad.id"  # nosec B608
            ]
            project = ad_summary
        else:
            queries = [
                f"SELECT {KEYWORD_FIELDS} FROM ad_group_criterion WHERE {condition} AND ad_group_criterion.type = 'KEYWORD' ORDER BY ad_group_criterion.criterion_id"  # nosec B608
            ]
            if "campaign" in v:
                fields = "campaign.resource_name, campaign_criterion.resource_name, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type, campaign_criterion.status, campaign_criterion.negative"
                queries.append(
                    f"SELECT {fields} FROM campaign_criterion WHERE {condition} AND campaign_criterion.type = 'KEYWORD' ORDER BY campaign_criterion.criterion_id"  # nosec B608
                )
            project = keyword_summary
            extras["currency_code"] = account["currency_code"]
    else:
        row = campaign_row(ctx, send, v["campaign"])
        c = row["campaign"]
        setting = c.get("geoTargetTypeSetting", {})
        extras = {
            "campaign": v["campaign"],
            "location_options": {
                "positive_geo_target_type": setting.get("positiveGeoTargetType", "UNSPECIFIED"),
                "negative_geo_target_type": setting.get("negativeGeoTargetType", "UNSPECIFIED"),
            },
            "network_settings": networks(c),
        }
        queries = [
            f"SELECT {CRITERION_FIELDS} FROM campaign_criterion WHERE campaign_criterion.campaign = {literal(v['campaign'])} AND campaign_criterion.type IN ('LOCATION', 'AD_SCHEDULE', 'LANGUAGE') AND campaign_criterion.status != 'REMOVED' ORDER BY campaign_criterion.criterion_id"  # nosec B608
        ]
        project = targeting_summary
    items, cursor, truncated = paged(ctx, send, queries, project)
    return {**common, **extras, "items": items, "next_cursor": cursor, "truncated": truncated}
