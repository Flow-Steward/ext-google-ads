"""Provider-only pinned HTTPS with bounded response reads and safe failures."""

from __future__ import annotations
from dataclasses import dataclass, field
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from flowsteward_extension_sdk import Request, open_pinned_url
from .errors import AdsError


@dataclass(frozen=True)
class WireRequest:
    method: str
    url: str
    headers: dict = field(repr=False)
    body: dict | None = None
    timeout_seconds: float = 15.0
    write: bool = False


@dataclass(frozen=True)
class Reply:
    body: object
    request_id: str | None = None


class PinnedTransport:
    def __init__(self, max_response_bytes: int = 8 * 1024 * 1024):
        self.max_response_bytes = max_response_bytes

    def __call__(self, request: WireRequest) -> Reply:
        parsed = urlsplit(request.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"googleads.googleapis.com", "openidconnect.googleapis.com"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.fragment
            or parsed.query
        ):
            raise AdsError("invalid_payload", "The provider destination is not allowed.")
        data = (
            None
            if request.body is None
            else json.dumps(request.body, allow_nan=False, separators=(",", ":")).encode()
        )
        req = Request(request.url, data=data, headers=request.headers, method=request.method)
        try:
            with open_pinned_url(
                req, timeout_seconds=request.timeout_seconds, purpose="Google Ads API"
            ) as response:
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise AdsError(
                        "outcome_unknown" if request.write else "validation_failed",
                        "The provider response exceeds the safe limit.",
                        unknown=request.write,
                    )
                result = json.loads(raw)
                headers = getattr(response, "headers", {})
                return Reply(result, headers.get("request-id"))
        except AdsError:
            raise
        except HTTPError as exc:
            if request.write and exc.code >= 500:
                raise AdsError(
                    "outcome_unknown",
                    "The provider write outcome is unknown; do not repeat it automatically.",
                    unknown=True,
                ) from None
            code = {
                401: "authorization_required",
                403: "permission_denied",
                404: "resource_not_found",
                429: "rate_limited",
            }.get(exc.code, "validation_failed" if exc.code < 500 else "provider_unavailable")
            raise AdsError(
                code,
                "Google refused the request; review access, configuration and quotas.",
                retryable=not request.write and exc.code in {429, 500, 502, 503, 504},
            ) from None
        except (TimeoutError, OSError, URLError, ValueError):
            raise AdsError(
                "outcome_unknown" if request.write else "timeout",
                "The provider write outcome is unknown; do not repeat it automatically."
                if request.write
                else "The provider request did not complete safely.",
                retryable=not request.write,
                unknown=request.write,
            ) from None
