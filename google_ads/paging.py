"""Stateless scoped cursors retain provider-page offsets without a cache service."""

from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from .errors import AdsError


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _scope(ctx, query):
    return [
        ctx.account_id,
        ctx.project_id,
        ctx.connection_id,
        ctx.customer,
        ctx.manager,
        ctx.revision,
        ctx.operation,
        query,
    ]


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def encode(ctx, query, state):
    data = {
        "v": 1,
        "scope": digest(_scope(ctx, query)),
        "expires": int(time.time()) + 3600,
        "state": state,
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(ctx.token.encode(), b"google-ads-cursor-v1:" + raw, hashlib.sha256).digest()
    cursor = _b64(raw) + "." + _b64(mac)
    if len(cursor) > 8192:
        raise AdsError(
            "validation_failed", "The continuation exceeds the safe limit; narrow the filters."
        )
    return cursor


def decode(ctx, query):
    token = ctx.values.get("cursor")
    if not token:
        return {}
    try:
        raw64, mac64 = token.split(".")
        raw = base64.urlsafe_b64decode(raw64 + "=" * (-len(raw64) % 4))
        mac = base64.urlsafe_b64decode(mac64 + "=" * (-len(mac64) % 4))
        expected = hmac.new(
            ctx.token.encode(), b"google-ads-cursor-v1:" + raw, hashlib.sha256
        ).digest()
        data = json.loads(raw)
        if (
            not hmac.compare_digest(mac, expected)
            or data.get("v") != 1
            or data.get("scope") != digest(_scope(ctx, query))
            or data["expires"] < time.time()
            or not isinstance(data["state"], dict)
        ):
            raise ValueError
        return data["state"]
    except (ValueError, TypeError, KeyError):
        raise AdsError(
            "state_conflict",
            "The cursor expired or its account/query changed; restart the read.",
            restart=True,
        ) from None


def window(ctx, query, items, *, incomplete=False):
    state = decode(ctx, query)
    fingerprint = digest(items)
    if state and state.get("fingerprint") != fingerprint:
        raise AdsError(
            "state_conflict", "The discovery result changed; restart the read.", restart=True
        )
    offset = state.get("offset", 0)
    size = ctx.values.get("page_size", 100)
    result = items[offset : offset + size]
    remaining = offset + len(result) < len(items)
    cursor = (
        encode(ctx, query, {"offset": offset + len(result), "fingerprint": fingerprint})
        if remaining and not incomplete
        else None
    )
    return result, cursor, incomplete
