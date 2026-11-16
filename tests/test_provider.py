"""Provider wire contracts for identity and current account metadata."""

from pathlib import Path
import yaml
from test_boundary import fixture

ROOT = Path(__file__).resolve().parents[1]


def test_get_account_uses_selected_token_manager_and_google_metadata():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    seen = []

    def send(request):
        seen.append(request)
        return Reply(
            [
                {
                    "results": [
                        {
                            "customer": {
                                "id": "1234567890",
                                "resourceName": "customers/1234567890",
                                "descriptiveName": "Synthetic client account",
                                "manager": False,
                                "testAccount": True,
                                "status": "ENABLED",
                                "currencyCode": "EUR",
                                "timeZone": "Europe/Vilnius",
                                "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
                            }
                        }
                    ]
                }
            ]
        )

    result = dispatch(fixture(), transport=send)
    expected = yaml.safe_load((ROOT / "examples/get_account.yaml").read_text())["success"][
        "response"
    ]
    assert result == expected
    assert len(seen) == 1
    req = seen[0]
    assert (
        req.url
        == "https://googleads.googleapis.com/v26/customers/1234567890/googleAds:searchStream"
    )
    assert req.headers["Authorization"] == "Bearer synthetic-access-token"
    assert req.headers["login-customer-id"] == "9876543210"
    assert "developer-token" not in req.headers
    assert req.method == "POST"
    assert req.body["query"].startswith("SELECT customer.")


def test_bind_only_reads_saved_pair_and_does_not_write_config():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    p = fixture("bind_ads_account")
    seen = []

    def send(req):
        seen.append(req)
        return Reply(
            [
                {
                    "results": [
                        {
                            "customer": {
                                "id": "1234567890",
                                "resourceName": "customers/1234567890",
                                "manager": False,
                                "testAccount": True,
                                "currencyCode": "EUR",
                                "timeZone": "Europe/Vilnius",
                                "status": "ENABLED",
                            }
                        }
                    ]
                }
            ]
        )

    result = dispatch(p, transport=send)
    assert result["ok"] is True
    assert result["result"]["customer_id"] == "1234567890"
    assert "commands" not in result and "project_state_updates" not in result
    assert all("mutate" not in req.url for req in seen)


def test_identity_accepts_host_callback_projection_without_connection_type():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    p = fixture("verify_google_identity")
    p["action"]["target"]["connection"].pop("connection_type")
    p["action"]["target"]["connection"]["config"] = {}
    seen = []

    def send(req):
        seen.append(req)
        return Reply(
            {"sub": "synthetic-subject", "email": "user@example.invalid", "email_verified": True}
        )

    result = dispatch(p, transport=send)
    assert result == {
        "ok": True,
        "result": {
            "subject": "synthetic-subject",
            "verified_email": "user@example.invalid",
            "verified_display_name": "user@example.invalid",
            "safe_metadata": {},
            "health": "ok",
        },
    }
    assert seen[0].url == "https://openidconnect.googleapis.com/v1/userinfo"
    assert seen[0].method == "GET"
    assert "login-customer-id" not in seen[0].headers


def test_identity_refuses_unverified_email_and_does_not_echo_token():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    result = dispatch(
        fixture("verify_google_identity"),
        transport=lambda req: Reply(
            {"sub": "id", "email": "user@example.invalid", "email_verified": False}
        ),
    )
    assert result["ok"] is False
    assert result["error_code"] == "authorization_required"
    assert "synthetic-access-token" not in str(result)
