"""Map bounded Google error enums without echoing raw provider messages."""

import json
import re
from flowsteward_extension_sdk import parse_retry_after
from .errors import AdsError


def request_id(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) else None
    )


def provider_failure(status, raw, headers, *, write=False):
    details = []
    try:
        parsed = json.loads(raw) if len(raw) <= 65536 else {}
        root = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        details = root.get("details", []) if isinstance(root, dict) else []
    except (ValueError, RecursionError):
        pass
    enums = []
    policy = False
    for detail in details[:100] if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        for item in (
            detail.get("errors", [])[:100] if isinstance(detail.get("errors", []), list) else []
        ):
            if not isinstance(item, dict) or not isinstance(item.get("errorCode"), dict):
                continue
            for field, value in item["errorCode"].items():
                if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value):
                    enums.append(value)
                    policy = policy or "policy" in str(field).lower()
    selected = next(iter(enums), None)
    code = {
        401: "authorization_required",
        403: "permission_denied",
        404: "resource_not_found",
        429: "rate_limited",
    }.get(status, "validation_failed" if status < 500 else "provider_unavailable")
    message = "Google refused the request; review access, configuration and quotas."
    retryable = not write and status in {429, 500, 502, 503, 504}
    restart = False
    values = set(enums)
    if "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" in values:
        code = "production_access_required"
        retryable = False
        message = (
            "This Cloud project needs Explorer, Basic or Standard access for production customers."
        )
    elif (
        values
        & {
            "EU_POLITICAL_ADVERTISING_DECLARATION_REQUIRED",
            "MISSING_EU_POLITICAL_ADVERTISING_SELF_DECLARATION",
        }
        or policy
    ):
        code = "policy_violation"
        retryable = False
        message = "Google Ads requires a policy or EU political-advertising declaration correction. Complete it in Google Ads; the affected campaign list is not determined."
    elif values & {"NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT", "BID_TOO_MANY_FRACTIONAL_DIGITS"}:
        code = "validation_failed"
        retryable = False
        message = "Google rejected the monetary precision; use the account currency's permitted unit without rounding."
    elif values & {"RESOURCE_EXHAUSTED", "EXCESSIVE_LONG_TERM_QUERY_RESOURCE_CONSUMPTION"}:
        code = "quota_exceeded"
        retryable = False
        message = "The project/customer quota is exhausted; do not repeatedly retry or change credentials."
    elif values & {
        "RESOURCE_TEMPORARILY_EXHAUSTED",
        "EXCESSIVE_SHORT_TERM_QUERY_RESOURCE_CONSUMPTION",
    }:
        code = "rate_limited"
        retryable = not write
    elif values & {"EXPIRED_PAGE_TOKEN", "INVALID_PAGE_TOKEN"}:
        code = "state_conflict"
        retryable = False
        restart = True
        message = "The provider cursor expired or became invalid; restart the read explicitly."
    elif values & {"OAUTH_TOKEN_INVALID", "OAUTH_TOKEN_EXPIRED", "OAUTH_TOKEN_REVOKED"}:
        code = "authorization_required"
        retryable = False
        message = "Google authorization is unavailable; reconnect the selected account."
    elif values & {"CUSTOMER_NOT_FOUND", "CUSTOMER_NOT_ENABLED"}:
        code = "account_access_lost"
        retryable = False
        message = "The configured advertising customer is unavailable."
    unknown = write and status >= 500
    if unknown:
        code = "outcome_unknown"
        retryable = False
        message = "The provider write outcome is unknown; reconcile before retrying."
    error = AdsError(
        code,
        message,
        retryable=retryable,
        unknown=unknown,
        restart=restart,
        no_effect=write and 400 <= status < 500,
        retry_after=parse_retry_after(headers.get("Retry-After")),
    )
    error.request_id = request_id(headers.get("request-id"))
    error.provider_error_code = selected
    return error
