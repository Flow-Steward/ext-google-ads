"""OpenID identity and actual bound account metadata; never saved as authority."""

# GAQL uses closed field/source constants and resource literals escaped by reads.literal.

import re
import time
import secrets
from .context import Context
from .transport import WireRequest
from .errors import AdsError

API_VERSION = "v26"
BASE_URL = "https://googleads.googleapis.com/v26"


def call(ctx: Context, send, path: str, body=None, *, customer: str | None = None, write=False):
    headers = {
        "Authorization": f"Bearer {ctx.token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if ctx.manager:
        headers["login-customer-id"] = ctx.manager
    for attempt in range(3):
        left = ctx.deadline - time.monotonic()
        if left <= 0:
            raise AdsError("timeout", "The operation deadline expired before dispatch.")
        if write:
            ctx.effect_status = "sent_unknown"
        try:
            reply = send(
                WireRequest(
                    "GET" if body is None else "POST",
                    f"{BASE_URL}/{path}",
                    headers,
                    body,
                    min(15.0, left),
                    write,
                )
            )
        except AdsError as error:
            if write or not error.retryable or attempt == 2:
                raise
            delay = max(error.retry_after or 0, 0.25 * (2**attempt)) + secrets.randbelow(101) / 1000
            if time.monotonic() + delay >= ctx.deadline:
                raise AdsError(
                    "timeout", "The read retry would exceed its operation deadline."
                ) from None
            time.sleep(delay)
            continue
        if write:
            ctx.effect_status = "confirmed"
        return reply
    raise AdsError("timeout", "The bounded read retries were exhausted.")


def get_account(ctx: Context, send, *, allow_manager: bool = False) -> dict:
    fields = "customer.id, customer.resource_name, customer.descriptive_name, customer.manager, customer.test_account, customer.status, customer.currency_code, customer.time_zone, customer.contains_eu_political_advertising"
    reply = call(
        ctx,
        send,
        f"customers/{ctx.customer}/googleAds:searchStream",
        {"query": f"SELECT {fields} FROM customer LIMIT 1"},  # nosec B608
    )
    batches = reply.body
    if not isinstance(batches, list):
        raise AdsError("provider_unavailable", "Invalid account metadata response.")
    rows = [
        row
        for batch in batches
        if isinstance(batch, dict)
        for row in batch.get("results", [])
        if isinstance(row, dict)
    ]
    if len(rows) != 1 or not isinstance(rows[0].get("customer"), dict):
        raise AdsError("account_access_lost", "The selected advertising account is unavailable.")
    c = rows[0]["customer"]
    if (
        str(c.get("id")) != ctx.customer
        or c.get("resourceName") != f"customers/{ctx.customer}"
        or (c.get("manager", False) and not allow_manager)
    ):
        raise AdsError(
            "account_access_lost", "A directly accessible advertising customer is required."
        )
    result = {
        "customer_id": ctx.customer,
        "connection_id": ctx.connection_id,
        "api_version": API_VERSION,
        "account": {
            "resource_name": c["resourceName"],
            "descriptive_name": c.get("descriptiveName"),
            "manager": c.get("manager", False),
            "test_account": c.get("testAccount", False),
            "status": c.get("status", "UNSPECIFIED"),
            "currency_code": c.get("currencyCode"),
            "time_zone": c.get("timeZone"),
            "contains_eu_political_advertising": c.get("containsEuPoliticalAdvertising"),
        },
    }
    return result


def verify_identity(ctx: Context, send) -> dict:
    reply = send(
        WireRequest(
            "GET",
            "https://openidconnect.googleapis.com/v1/userinfo",
            {"Authorization": f"Bearer {ctx.token}", "Accept": "application/json"},
            timeout_seconds=15.0,
        )
    )
    p = reply.body
    if not isinstance(p, dict):
        raise AdsError("authorization_required", "Google identity could not be verified.")
    subject, email = p.get("sub"), p.get("email")
    if (
        not isinstance(subject, str)
        or not subject
        or subject.strip() != subject
        or len(subject.encode()) > 512
        or not isinstance(email, str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+", email)
        or len(email.encode()) > 320
        or p.get("email_verified") is not True
    ):
        raise AdsError("authorization_required", "Google identity could not be verified.")
    return {
        "subject": subject,
        "verified_email": email,
        "verified_display_name": email,
        "safe_metadata": {},
        "health": "ok",
    }
