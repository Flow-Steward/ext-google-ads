"""Google error enums, bounded read retries and definite/unknown write outcomes."""

import io
import json
from urllib.error import HTTPError
import pytest
from test_transport import request
from test_boundary import fixture


@pytest.mark.parametrize(
    "field,enum,status,expected,retryable",
    [
        (
            "authorizationError",
            "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
            403,
            "production_access_required",
            False,
        ),
        (
            "mutateError",
            "EU_POLITICAL_ADVERTISING_DECLARATION_REQUIRED",
            400,
            "policy_violation",
            False,
        ),
        (
            "criterionError",
            "MISSING_EU_POLITICAL_ADVERTISING_SELF_DECLARATION",
            400,
            "policy_violation",
            False,
        ),
        (
            "campaignBudgetError",
            "NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT",
            400,
            "validation_failed",
            False,
        ),
        ("biddingError", "BID_TOO_MANY_FRACTIONAL_DIGITS", 400, "validation_failed", False),
        ("quotaError", "RESOURCE_EXHAUSTED", 429, "quota_exceeded", False),
        ("quotaError", "RESOURCE_TEMPORARILY_EXHAUSTED", 429, "rate_limited", True),
        ("requestError", "EXPIRED_PAGE_TOKEN", 400, "state_conflict", False),
    ],
)
def test_provider_error_catalogue_is_enum_driven_and_redacted(
    monkeypatch, field, enum, status, expected, retryable
):
    import google_ads.transport as mod
    from google_ads.errors import AdsError

    body = {
        "error": {
            "message": "sensitive-access-token",
            "details": [
                {
                    "@type": "type.googleapis.com/google.ads.googleads.v26.errors.GoogleAdsFailure",
                    "errors": [{"errorCode": {field: enum}, "message": "sensitive-access-token"}],
                }
            ],
        }
    }

    def fail(*a, **k):
        raise HTTPError(
            "https://googleads.googleapis.com/v26/x",
            status,
            "provider error",
            {"request-id": "safe_request_id", "Retry-After": "2"},
            io.BytesIO(json.dumps(body).encode()),
        )

    monkeypatch.setattr(mod, "open_pinned_url", fail)
    with pytest.raises(AdsError) as caught:
        mod.PinnedTransport()(request())
    error = caught.value
    assert error.code == expected
    assert error.retryable is retryable
    envelope = error.envelope()
    assert envelope["request_id"] == "safe_request_id"
    assert envelope["provider_error_code"] == enum
    assert "sensitive" not in str(envelope)
    if expected == "state_conflict":
        assert envelope["restart_required"] is True
    if expected == "policy_violation":
        assert "Google Ads" in envelope["error"]


def test_atomic_provider_rejection_proves_no_external_effect(monkeypatch):
    import google_ads.transport as mod
    from google_ads.errors import AdsError

    def fail(*a, **k):
        raise HTTPError(
            "https://googleads.googleapis.com/v26/x",
            400,
            "invalid",
            {},
            io.BytesIO(b'{"error":{}}'),
        )

    monkeypatch.setattr(mod, "open_pinned_url", fail)
    with pytest.raises(AdsError) as caught:
        mod.PinnedTransport()(request(write=True))
    assert caught.value.no_effect is True
    assert caught.value.envelope()["definitely_no_external_effect"] is True
    assert caught.value.retryable is False


def test_read_retry_is_bounded_and_uses_retry_after(monkeypatch):
    from google_ads.context import from_payload
    from google_ads.accounts import call
    from google_ads.transport import Reply
    from google_ads.errors import AdsError
    import google_ads.accounts as accounts

    sleeps = []
    attempts = []
    monkeypatch.setattr(accounts.time, "sleep", lambda delay: sleeps.append(delay))

    def send(req):
        attempts.append(req)
        if len(attempts) < 3:
            raise AdsError("rate_limited", "Try later.", retryable=True, retry_after=1.0)
        return Reply({"results": []})

    ctx = from_payload(fixture())
    result = call(
        ctx,
        send,
        "customers/1234567890/googleAds:search",
        {"query": "SELECT customer.id FROM customer"},
    )
    assert result.body == {"results": []}
    assert len(attempts) == 3
    assert len(sleeps) == 2 and all(delay >= 1 for delay in sleeps)


def test_daily_quota_exhaustion_is_not_retried(monkeypatch):
    from google_ads.context import from_payload
    from google_ads.accounts import call
    from google_ads.errors import AdsError

    seen = []

    def send(req):
        seen.append(req)
        raise AdsError("quota_exceeded", "Daily quota exhausted.")

    with pytest.raises(AdsError):
        call(
            from_payload(fixture()),
            send,
            "customers/1234567890/googleAds:search",
            {"query": "SELECT customer.id FROM customer"},
        )
    assert len(seen) == 1
