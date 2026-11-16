"""Bounded, pinned HTTPS and truthful ambiguous write failures."""

import io
import json
import pytest


def request(**changes):
    from google_ads.transport import WireRequest

    fields = dict(
        method="POST",
        url="https://googleads.googleapis.com/v26/customers/1234567890/googleAds:searchStream",
        headers={"Authorization": "Bearer sensitive"},
        body={"query": "SELECT customer.id FROM customer"},
        timeout_seconds=5.0,
        write=False,
    )
    fields.update(changes)
    return WireRequest(**fields)


def test_transport_uses_sdk_pinned_https_and_bounds_response(monkeypatch):
    import google_ads.transport as mod

    seen = []

    class Response(io.BytesIO):
        headers = {"request-id": "request_fixture"}

    def open_url(req, **kwargs):
        seen.append((req, kwargs))
        return Response(b'{"results":[]}')

    monkeypatch.setattr(mod, "open_pinned_url", open_url)
    reply = mod.PinnedTransport(max_response_bytes=64)(request())
    assert reply.body == {"results": []} and reply.request_id == "request_fixture"
    assert seen[0][1]["timeout_seconds"] == 5.0
    assert json.loads(seen[0][0].data)["query"].startswith("SELECT")


def test_response_overflow_is_refused(monkeypatch):
    import google_ads.transport as mod
    from google_ads.errors import AdsError

    monkeypatch.setattr(mod, "open_pinned_url", lambda *a, **k: io.BytesIO(b" " * 65))
    with pytest.raises(AdsError) as e:
        mod.PinnedTransport(max_response_bytes=64)(request())
    assert e.value.code == "validation_failed"


@pytest.mark.parametrize(
    "url",
    [
        "http://googleads.googleapis.com/v26/x",
        "https://evil.invalid/x",
        "https://googleads.googleapis.com@evil.invalid/x",
    ],
)
def test_wrong_origin_is_rejected_before_open(monkeypatch, url):
    import google_ads.transport as mod
    from google_ads.errors import AdsError

    def forbidden(*a, **k):
        pytest.fail("unsafe origin opened")

    monkeypatch.setattr(mod, "open_pinned_url", forbidden)
    with pytest.raises(AdsError):
        mod.PinnedTransport()(request(url=url))


@pytest.mark.parametrize("write,expected", [(False, "timeout"), (True, "outcome_unknown")])
def test_timeout_retains_unknown_write_truth(monkeypatch, write, expected):
    import google_ads.transport as mod
    from google_ads.errors import AdsError

    def timeout(*a, **k):
        raise TimeoutError("sensitive provider exception")

    monkeypatch.setattr(mod, "open_pinned_url", timeout)
    with pytest.raises(AdsError) as e:
        mod.PinnedTransport()(request(write=write))
    assert e.value.code == expected
    assert e.value.unknown is write
    assert "sensitive" not in str(e.value)


def test_wire_fractional_metrics_are_parsed_without_binary_float(monkeypatch):
    from decimal import Decimal
    import google_ads.transport as mod

    monkeypatch.setattr(
        mod,
        "open_pinned_url",
        lambda *a, **k: io.BytesIO(b'{"metrics":{"conversions":0.1234567890123456789}}'),
    )
    reply = mod.PinnedTransport()(request())
    assert reply.body["metrics"]["conversions"] == Decimal("0.1234567890123456789")
