"""Approved callable read path and native targeting review composition."""

from copy import deepcopy
from pathlib import Path
import json
import yaml
import pytest
from jinja2 import StrictUndefined, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from test_boundary import fixture

ROOT = Path(__file__).resolve().parents[1]
READS = {
    "get_account",
    "list_accessible_accounts",
    "list_manager_clients",
    "list_campaigns",
    "get_campaign",
    "list_ad_groups",
    "list_ads",
    "list_keywords",
    "list_targeting",
    "validate_search_campaign",
    "get_performance_report",
}


def load(name):
    return yaml.safe_load((ROOT / "artifacts/workflows" / (name + ".yaml")).read_text())


def test_approved_agent_reads_use_callable_workflows_and_project_slots():
    missing = []
    for name in sorted(READS):
        path = ROOT / "artifacts/workflows" / ("google_ads_read_" + name + ".yaml")
        if not path.is_file():
            missing.append(name)
            continue
        flow = yaml.safe_load(path.read_text())
        assert flow["settings"]["callable"]["enabled"] is True
        assert flow["settings"]["callable"]["side_effects"] == []
        step = next(s for s in flow["steps"] if s["step_kind"] == "connector")
        assert step["override"]["connector"]["action_id"] == name
        assert step["connection_binding_jsonb"] == {"slot": "client"}
    assert not missing, missing


def render(request, snapshot):
    flow = load("google_ads_targeting_with_approval")
    step = next(s for s in flow["steps"] if s["step_kind"] == "template")
    text = step["override"]["template"]["text"]
    return json.loads(
        ImmutableSandboxedEnvironment(undefined=StrictUndefined)
        .from_string(text)
        .render(request=request, snapshot=snapshot)
    )


def example():
    request = fixture("set_campaign_targeting")["action"]["input"]
    snapshot = {
        "customer_id": "1234567890",
        "connection_id": "conn_ads_client_a",
        "campaign": request["campaign_resource_name"],
        "items": [],
        "location_options": deepcopy(request["expected_current"]["location_options"]),
        "next_cursor": None,
        "truncated": False,
    }
    return request, snapshot


def test_targeting_review_verifies_expected_and_prepares_exact_saved_diff():
    request, snapshot = example()
    request["expected_current"]["geo_target_constants"] = ["geoTargetConstants/2440"]
    request["desired"]["geo_target_constants"] = ["geoTargetConstants/2840"]
    snapshot["items"] = [
        {"kind": "geo", "negative": False, "geo_target_constant": "geoTargetConstants/2440"},
        {"kind": "legacy_language", "language_constant": "languageConstants/1000"},
    ]
    review = render(request, snapshot)
    assert review["write_input"] == request
    assert review["additions"] == [{"family": "GEO", "value": "geoTargetConstants/2840"}]
    assert review["removals"] == [{"family": "GEO", "value": "geoTargetConstants/2440"}]
    assert review["location_changes"][0]["field"] == "positive_geo_target_type"
    flow = load("google_ads_targeting_with_approval")
    step = next(
        s
        for s in flow["steps"]
        if s["step_kind"] == "connector"
        and s["override"]["connector"]["action_id"] == "set_campaign_targeting"
    )
    assert all(
        value.startswith("state.ads_targeting_input.")
        for value in step["input_mapping_jsonb"].values()
    )
    assert not any(s["step_kind"] == "agent" for s in flow["steps"])


@pytest.mark.parametrize("case", ["stale", "incomplete", "wrong_customer"])
def test_targeting_review_stops_before_approval_for_unverified_snapshot(case):
    request, snapshot = example()
    if case == "stale":
        snapshot["location_options"]["positive_geo_target_type"] = "PRESENCE_OR_INTEREST"
    elif case == "incomplete":
        snapshot["next_cursor"] = "more"
    else:
        snapshot["customer_id"] = "1111111111"
    with pytest.raises(UndefinedError):
        render(request, snapshot)


def test_targeting_review_schedule_reset_shows_removal_without_language_changes():
    request, snapshot = example()
    interval = {"day": "MONDAY", "start_hour": 0, "start_minute": 0, "end_hour": 1, "end_minute": 0}
    request["expected_current"] = {"schedule": {"mode": "weekly", "intervals": [interval]}}
    request["desired"] = {"schedule": {"mode": "all_time"}}
    snapshot["items"] = [
        {"kind": "ad_schedule", **interval},
        {"kind": "legacy_language", "serving": False},
    ]
    review = render(request, snapshot)
    assert review["removals"] == [{"family": "SCHEDULE", "value": interval}]
    assert review["additions"] == []
