"""Finite GAQL reports with exact Decimal ratios and bounded inline rows."""

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
import json
import re
import time
from .accounts import get_account
from .reads import base, search, verify_refs
from .validation import reject
from .errors import AdsError

MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_ROWS = 10000
FIELDS = {
    "campaign": "campaign.resource_name",
    "ad_group": "ad_group.resource_name",
    "ad": "ad_group_ad.ad.resource_name",
    "keyword": "ad_group_criterion.resource_name",
    "search_term": "search_term_view.search_term",
    "date": "segments.date",
    "device": "segments.device",
}
SOURCES = {
    "account_summary": "customer",
    "campaign": "campaign",
    "ad_group": "ad_group",
    "ad": "ad_group_ad",
    "keyword": "keyword_view",
    "search_term": "search_term_view",
}
METRICS = {
    "impressions": "impressions",
    "clicks": "clicks",
    "cost_micros": "costMicros",
    "conversions": "conversions",
    "conversion_value": "conversionsValue",
}
GAQL = {
    "impressions": "metrics.impressions",
    "clicks": "metrics.clicks",
    "cost_micros": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "conversion_value": "metrics.conversions_value",
}
DEPENDENCIES = {
    "ctr": ("clicks", "impressions"),
    "average_cpc_micros": ("cost_micros", "clicks"),
    "cpa_micros": ("cost_micros", "conversions"),
    "roas": ("conversion_value", "cost_micros"),
}
PATHS = {
    "campaign": ("campaign", "resourceName"),
    "ad_group": ("adGroup", "resourceName"),
    "ad": ("adGroupAd", "ad", "resourceName"),
    "keyword": ("adGroupCriterion", "resourceName"),
    "search_term": ("searchTermView", "searchTerm"),
    "date": ("segments", "date"),
    "device": ("segments", "device"),
}


def invalid():
    raise AdsError(
        "provider_unavailable", "A provider report row contains invalid or unrepresentable values."
    )


def number(value, integer=False):
    # Production transport parses JSON fractional tokens directly into Decimal.
    if isinstance(value, bool) or isinstance(value, float):
        invalid()
    text = str(value)
    if integer:
        if not re.fullmatch(r"0|[1-9][0-9]{0,18}", text) or int(text) > 9223372036854775807:
            invalid()
        return text
    try:
        result = Decimal(text)
        if not result.is_finite() or len(text) > 128 or abs(result.adjusted()) > 126:
            invalid()
        fixed = format(result, "f")
        if len(fixed) > 128:
            invalid()
        return fixed
    except (InvalidOperation, ValueError):
        invalid()


def ratio(numerator, denominator):
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 160
        value = (numerator / denominator).quantize(
            Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
        )
        text = format(value, "f").rstrip("0").rstrip(".")
        if text in {"-0", ""}:
            text = "0"
        if len(text) > 128:
            invalid()
        return text


def project(row, dimensions, requested, needed):
    verify = {}
    for dim in dimensions:
        value = row
        for key in PATHS[dim]:
            if not isinstance(value, dict) or key not in value:
                invalid()
            value = value[key]
        if not isinstance(value, str):
            invalid()
        if dim == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                invalid()
        verify[dim] = value
    raw = row.get("metrics", {})
    values = {
        key: number(raw.get(METRICS[key], "0"), key in {"impressions", "clicks", "cost_micros"})
        for key in needed
    }
    metrics = {}
    for key in requested:
        if key in METRICS:
            metrics[key] = values[key]
        else:
            left, right = DEPENDENCIES[key]
            numerator = Decimal(values[left])
            denominator = Decimal(values[right])
            if key == "roas":
                numerator *= Decimal(1000000)
            metrics[key] = ratio(numerator, denominator)
    return {**verify, "metrics": metrics}


def execute(ctx, send):
    v = ctx.values
    try:
        start = date.fromisoformat(v["start_date"])
        end = date.fromisoformat(v["end_date"])
    except ValueError:
        reject("Use real calendar dates for the account-local report period.")
    if end < start or (end - start).days + 1 > 366:
        reject("Report periods must be ordered and contain at most366 inclusive days.")
    if len(set(v["metrics"])) != len(v["metrics"]):
        reject("Report metrics must be unique.")
    account = get_account(ctx, send)["account"]
    dimensions = v["dimensions"]
    requested = v["metrics"]
    needed = set()
    for metric in requested:
        needed.update(DEPENDENCIES[metric] if metric in DEPENDENCIES else [metric])
    fields = [FIELDS[key] for key in dimensions] + [GAQL[key] for key in sorted(needed)]
    # All fields/source/layouts are validated closed schema constants, dates are parsed above.
    query = f"SELECT {', '.join(fields)} FROM {SOURCES[v['report_type']]} WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"
    if dimensions:
        query += " ORDER BY " + ", ".join(FIELDS[key] for key in dimensions)
    rows = []
    token = ""
    seen = set()
    truncated = False
    used = 1024
    while True:
        if time.monotonic() >= ctx.deadline:
            truncated = True
            break
        try:
            page, next_token = search(ctx, send, query, token)
        except AdsError as error:
            if error.code == "timeout" and rows:
                truncated = True
                break
            raise
        for row in page:
            if len(rows) >= MAX_ROWS or time.monotonic() >= ctx.deadline:
                truncated = True
                break
            verify_refs(ctx, row)
            item = project(row, dimensions, requested, needed)
            size = len(json.dumps(item, ensure_ascii=False).encode()) + 2
            if used + size > MAX_REPORT_BYTES:
                truncated = True
                break
            used += size
            rows.append(item)
        if truncated or not next_token:
            break
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        if next_token in seen or next_token == token:
            raise AdsError("provider_unavailable", "The provider repeated a report page cursor.")
        seen.add(next_token)
        token = next_token
    return {
        **base(ctx),
        "report_type": v["report_type"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "time_zone": account["time_zone"],
        "currency_code": account["currency_code"],
        "dimensions": dimensions,
        "metrics": requested,
        "rows": rows,
        "complete": not truncated,
        "truncated": truncated,
        "next_cursor": None,
        "narrowing_instruction": "Narrow the date range or dimensions and run a new report."
        if truncated
        else None,
        "search_term_privacy_limited": v["report_type"] == "search_term",
        "conversions_may_be_delayed": True,
    }
