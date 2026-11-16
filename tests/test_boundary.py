"""Runtime refusals must happen before any provider call."""

from pathlib import Path
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]


def fixture(name="get_account"):
    payload = yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())["success"]["request"]
    payload["action"]["target"]["connection"]["secrets"] = {
        "access_token": "synthetic-access-token"
    }
    return payload


def dispatch(payload):
    from google_ads.runtime import dispatch as run

    def forbidden(*args, **kwargs):
        pytest.fail("Rejected request reached the provider")

    return run(payload, transport=forbidden)


@pytest.mark.parametrize("value", [None, "v1", "extension_host_v1"])
def test_invalid_host_contract_never_reaches_provider(value):
    p = fixture()
    p["contract_version"] = value
    assert dispatch(p)["error_code"] == "invalid_host_envelope"


def test_missing_execution_scope_never_reaches_provider():
    p = fixture()
    del p["runtime_context"]["step_execution_id"]
    assert dispatch(p)["error_code"] == "invalid_host_envelope"


def test_write_alias_is_not_dispatchable():
    p = fixture()
    p["action"]["action_id"] = "invoke_tool"
    p["action"]["input"] = {"tool_name": "create_search_campaign"}
    assert dispatch(p)["error_code"] == "invalid_payload"


@pytest.mark.parametrize(
    "key",
    [
        "customer_id",
        "login_customer_id",
        "external_effect_id",
        "access_token",
        "endpoint_url",
        "gaql",
    ],
)
def test_unknown_input_and_authority_fields_rejected(key):
    p = fixture()
    p["action"]["input"][key] = "forged"
    assert dispatch(p)["error_code"] == "invalid_payload"


@pytest.mark.parametrize("change", ["missing_token", "disconnected", "wrong_type"])
def test_unauthorized_connection_never_reaches_provider(change):
    p = fixture()
    c = p["action"]["target"]["connection"]
    if change == "missing_token":
        c["secrets"] = {}
    elif change == "disconnected":
        c["config"]["oauth"]["lifecycle_status"] = "disconnected"
    else:
        c["connection_type"] = "foreign_connection"
    assert dispatch(p)["ok"] is False


def test_write_without_claim_refused_before_any_http():
    p = fixture("create_search_campaign")
    del p["runtime_context"]["external_effect_id"]
    assert dispatch(p)["error_code"] == "external_effect_claim_required"


def test_stale_customer_assertion_refused_before_any_http():
    p = fixture("create_search_campaign")
    p["action"]["input"]["expected_customer_id"] = "1111111111"
    assert dispatch(p)["error_code"] == "state_conflict"


def test_unbound_account_refused_before_any_http():
    p = fixture()
    del p["action"]["target"]["connection"]["config"]["customer_id"]
    assert dispatch(p)["error_code"] == "account_not_bound"


@pytest.mark.parametrize("value", [[], {}, 123, None])
def test_nonstring_action_id_is_a_safe_refusal(value):
    p = fixture()
    p["action"]["action_id"] = value
    assert dispatch(p)["error_code"] == "invalid_payload"


def test_disagreeing_project_context_refused():
    p = fixture()
    p["action"]["context"]["project_id"] = "foreign_project"
    assert dispatch(p)["error_code"] == "invalid_host_envelope"


def test_test_run_suppresses_write_without_provider_access():
    p = fixture("create_search_campaign")
    p["runtime_context"]["test_mode"] = True
    response = dispatch(p)
    assert response["ok"] is True
    assert response["external_effect_status"] == "suppressed"
    assert response["definitely_no_external_effect"] is True


def test_unexpected_provider_exception_is_redacted():
    from google_ads.runtime import dispatch as run

    def broken(req):
        raise RuntimeError("sensitive-access-token")

    result = run(fixture(), transport=broken)
    assert result["error_code"] == "internal_error"
    assert "sensitive" not in str(result)
