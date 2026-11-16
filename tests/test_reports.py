"""Finite report layouts, Decimal arithmetic and honest inline bounds."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import yaml
import pytest
from test_boundary import fixture
from test_reads import Provider, CAMPAIGN, GROUP

RAW = {
    "campaign": {"resourceName": CAMPAIGN},
    "adGroup": {"resourceName": GROUP},
    "adGroupAd": {"ad": {"resourceName": "customers/1234567890/ads/3001"}},
    "adGroupCriterion": {"resourceName": "customers/1234567890/adGroupCriteria/2001~4001"},
    "searchTermView": {"searchTerm": "synthetic query"},
    "segments": {"date": "2026-11-01", "device": "MOBILE"},
    "metrics": {
        "impressions": "1000",
        "clicks": "25",
        "costMicros": "5000000",
        "conversions": Decimal("2.5"),
        "conversionsValue": Decimal("25.0"),
    },
}


class Reports(Provider):
    def __init__(self):
        super().__init__()
        self.rows = [deepcopy(RAW)]
        self.next = ""
        self.queries = []

    def __call__(self, req):
        from google_ads.transport import Reply

        query = (req.body or {}).get("query", "")
        if "metrics." in query:
            self.queries.append(query)
            return Reply({"results": deepcopy(self.rows), "nextPageToken": self.next})
        return super().__call__(req)


def test_campaign_report_matches_example_decimal_units():
    from google_ads.runtime import dispatch

    response = dispatch(fixture("get_performance_report"), transport=Reports())
    expected = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "examples/get_performance_report.yaml").read_text()
    )["success"]["response"]
    assert response == expected


SCHEMAS = yaml.safe_load(
    (
        Path(__file__).resolve().parents[1] / "schemas/inputs/get_performance_report.schema.yaml"
    ).read_text()
)["oneOf"]
LAYOUTS = [
    (item["properties"]["report_type"]["const"], dims)
    for item in SCHEMAS
    for dims in item["properties"]["dimensions"]["enum"]
]


@pytest.mark.parametrize("kind,dimensions", LAYOUTS)
def test_all_24_layouts_have_exact_projection_and_no_raw_gaql(kind, dimensions):
    from google_ads.runtime import dispatch

    provider = Reports()
    p = fixture("get_performance_report")
    p["action"]["input"].update(report_type=kind, dimensions=dimensions, metrics=["clicks"])
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    assert set(response["result"]["rows"][0]) == set(dimensions) | {"metrics"}
    assert response["result"]["rows"][0]["metrics"] == {"clicks": "25"}
    assert response["result"]["search_term_privacy_limited"] is (kind == "search_term")
    assert "BETWEEN '2026-11-01' AND '2026-11-07'" in provider.queries[0]
    assert "page_size" not in provider.queries[0]


@pytest.mark.parametrize(
    "patch",
    [
        {"start_date": "2026-02-30"},
        {"start_date": "2026-11-08"},
        {"start_date": "2025-01-01"},
        {"metrics": ["clicks", "clicks"]},
        {"dimensions": ["campaign", "keyword"]},
    ],
)
def test_invalid_report_calendar_layout_or_duplicate_metrics_never_queries(patch):
    from google_ads.runtime import dispatch

    provider = Reports()
    p = fixture("get_performance_report")
    p["action"]["input"].update(patch)
    response = dispatch(p, transport=provider)
    assert response["error_code"] in {"validation_failed", "invalid_payload"}
    assert not provider.queries


def test_zero_denominators_produce_null_and_lossless_int64_is_preserved():
    from google_ads.runtime import dispatch

    provider = Reports()
    provider.rows[0]["metrics"].update(
        impressions="9223372036854775807", clicks="0", costMicros="0", conversions=Decimal("0")
    )
    response = dispatch(fixture("get_performance_report"), transport=provider)
    assert response["ok"], response
    metrics = response["result"]["rows"][0]["metrics"]
    assert metrics["impressions"] == "9223372036854775807" and metrics["ctr"] == "0"
    assert all(metrics[key] is None for key in ["average_cpc_micros", "cpa_micros", "roas"])


def test_ratio_rounding_is_12_fractional_places_half_even():
    from google_ads.runtime import dispatch

    provider = Reports()
    provider.rows[0]["metrics"].update(
        impressions="6",
        clicks="1",
        costMicros="1",
        conversions=Decimal("3"),
        conversionsValue=Decimal("0.000001"),
    )
    response = dispatch(fixture("get_performance_report"), transport=provider)
    assert response["ok"], response
    metrics = response["result"]["rows"][0]["metrics"]
    assert metrics["ctr"] == "0.166666666667"
    assert metrics["cpa_micros"] == "0.333333333333"
    assert metrics["roas"] == "1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("clicks", "9223372036854775808"),
        ("impressions", "-1"),
        ("costMicros", "1.5"),
        ("conversions", Decimal("NaN")),
    ],
)
def test_invalid_provider_numbers_are_errors_not_empty_reports(field, value):
    from google_ads.runtime import dispatch

    provider = Reports()
    provider.rows[0]["metrics"][field] = value
    response = dispatch(fixture("get_performance_report"), transport=provider)
    assert response["ok"] is False
    assert response["error_code"] == "provider_unavailable"


def test_row_limit_returns_explicit_incomplete_without_continuation_service():
    from google_ads.runtime import dispatch

    provider = Reports()
    provider.rows = [deepcopy(RAW) for _ in range(10000)]
    provider.next = "provider-page-two"
    p = fixture("get_performance_report")
    p["action"]["input"]["metrics"] = ["clicks"]
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    result = response["result"]
    assert len(result["rows"]) == 10000
    assert result["truncated"] is True and result["complete"] is False
    assert result["next_cursor"] is None and result["narrowing_instruction"]
    assert len(provider.queries) == 1


def test_byte_limit_returns_valid_partial_result(monkeypatch):
    from google_ads.runtime import dispatch
    import google_ads.reports as reports

    monkeypatch.setattr(reports, "MAX_REPORT_BYTES", 1800)
    provider = Reports()
    provider.rows = [deepcopy(RAW) for _ in range(20)]
    response = dispatch(fixture("get_performance_report"), transport=provider)
    assert response["ok"], response
    assert response["result"]["truncated"] is True
    assert 0 < len(response["result"]["rows"]) < 20
    assert len(json.dumps(response).encode()) < 4096
