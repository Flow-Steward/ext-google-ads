"""Atomic Search creation, validate-only, PAUSED safety and local semantics."""

from copy import deepcopy
from pathlib import Path
import yaml
import pytest
from test_boundary import fixture
from test_reads import Provider

ROOT = Path(__file__).resolve().parents[1]


class Creator(Provider):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.timeout = False

    def __call__(self, request):
        from google_ads.transport import Reply

        if not request.url.endswith("googleAds:mutate"):
            return super().__call__(request)
        self.writes.append(request)
        if self.timeout:
            raise TimeoutError("sensitive network detail")
        if request.body["validateOnly"]:
            return Reply({}, "synthetic-google-validation-001")
        expected = yaml.safe_load((ROOT / "examples/create_search_campaign.yaml").read_text())[
            "success"
        ]["response"]["result"]["resource_mapping"]
        rows = []
        types = {
            "budget": ("campaignBudgetResult", "campaignBudget"),
            "campaign": ("campaignResult", "campaign"),
            "ad_group": ("adGroupResult", "adGroup"),
            "ad": ("adGroupAdResult", "adGroupAd"),
            "keyword": ("adGroupCriterionResult", "adGroupCriterion"),
            "criterion": ("campaignCriterionResult", "campaignCriterion"),
        }
        for row in expected:
            result_key, entity = types[row["kind"]]
            value = {"resourceName": row["resource_name"]}
            if row["status"] != "NOT_APPLICABLE":
                value[entity] = {"resourceName": row["resource_name"], "status": row["status"]}
            rows.append({result_key: value})
        return Reply({"mutateOperationResponses": rows}, "synthetic-google-request-001")


@pytest.mark.parametrize("name", ["create_search_campaign", "validate_search_campaign"])
def test_search_plan_matches_public_result_and_atomic_wire(name):
    from google_ads.runtime import dispatch

    provider = Creator()
    result = dispatch(fixture(name), transport=provider)
    expected = yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())["success"][
        "response"
    ]
    assert result == expected
    assert len(provider.writes) == 1
    req = provider.writes[0]
    assert req.body["partialFailure"] is False
    assert req.body["validateOnly"] is (name == "validate_search_campaign")
    assert req.write is (name == "create_search_campaign")
    operations = req.body["mutateOperations"]
    assert len(operations) == 9
    budget = operations[0]["campaignBudgetOperation"]["create"]
    assert budget["explicitlyShared"] is False and budget["period"] == "DAILY"
    assert budget["amountMicros"] == "20000000"
    for operation in operations:
        for key in ("campaignOperation", "adGroupOperation", "adGroupAdOperation"):
            if key in operation:
                assert operation[key]["create"]["status"] == "PAUSED"
        if "adGroupCriterionOperation" in operation:
            assert operation["adGroupCriterionOperation"]["create"]["status"] == "ENABLED"
    assert "language" not in str(operations)
    assert "developer-token" not in req.headers


def test_ambiguous_create_timeout_is_not_retried():
    from google_ads.runtime import dispatch

    provider = Creator()
    provider.timeout = True
    result = dispatch(fixture("create_search_campaign"), transport=provider)
    assert result["error_code"] == "outcome_unknown"
    assert result["external_effect_status"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False
    assert result["retryable"] is False
    assert len(provider.writes) == 1
    assert "sensitive" not in str(result)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_key",
        "reserved_key",
        "duplicate_keyword",
        "duplicate_asset",
        "missing_cpc",
        "incompatible_cpc",
        "invalid_date",
        "bad_url",
        "overlap",
        "end_24_minutes",
        "currency",
    ],
)
def test_invalid_search_semantics_never_send_mutate(case):
    from google_ads.runtime import dispatch

    p = fixture("create_search_campaign")
    s = p["action"]["input"]["specification"]
    if case == "duplicate_key":
        s["ad_groups"][1]["key"] = s["ad_groups"][0]["key"]
    elif case == "reserved_key":
        s["ad_groups"][0]["key"] = "campaign"
    elif case == "duplicate_keyword":
        s["ad_groups"][0]["keywords"].append(
            {**s["ad_groups"][0]["keywords"][0], "key": "other_key"}
        )
    elif case == "duplicate_asset":
        s["ad_groups"][0]["ads"][0]["content"]["headlines"][1] = deepcopy(
            s["ad_groups"][0]["ads"][0]["content"]["headlines"][0]
        )
    elif case == "missing_cpc":
        s["ad_groups"][0].pop("cpc_bid_micros")
    elif case == "incompatible_cpc":
        s["bidding"] = {"strategy": "MAXIMIZE_CLICKS"}
    elif case == "invalid_date":
        s["start_date_time"] = "2026-02-30 12:00:00"
    elif case == "bad_url":
        s["ad_groups"][0]["ads"][0]["content"]["final_urls"] = [
            "https://user:password@example.invalid/"
        ]
    elif case == "currency":
        s["currency_code"] = "USD"
    else:
        interval = {
            "day": "MONDAY",
            "start_hour": 9,
            "start_minute": 0,
            "end_hour": 17,
            "end_minute": 0,
        }
        s["targeting"]["schedule"] = {"mode": "weekly", "intervals": [interval]}
        if case == "overlap":
            s["targeting"]["schedule"]["intervals"].append({**interval, "start_hour": 10})
        else:
            interval.update(end_hour=24, end_minute=15)
    provider = Creator()
    result = dispatch(p, transport=provider)
    assert result["ok"] is False, case
    assert not provider.writes, case


def test_expanded_mutate_limit_counts_every_nested_operation():
    from google_ads.runtime import dispatch

    p = fixture("create_search_campaign")
    s = p["action"]["input"]["specification"]
    s["ad_groups"][0]["keywords"] = [
        {"key": f"kw_{i}", "text": f"service {i}", "match_type": "EXACT"} for i in range(10000)
    ]
    provider = Creator()
    result = dispatch(p, transport=provider)
    assert result["error_code"] == "validation_failed"
    assert not provider.writes


@pytest.fixture(autouse=True)
def fixed_account_clock(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import google_ads.validation as validation

    monkeypatch.setattr(
        validation, "local_now", lambda zone: datetime(2026, 11, 16, 12, 0, tzinfo=ZoneInfo(zone))
    )
