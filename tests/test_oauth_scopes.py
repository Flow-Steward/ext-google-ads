"""Required OAuth scopes are written the way Google grants them.

Flow Steward compares the scopes a connection requires with the token response's `scope`
field string by string. Google answers with full scope URLs: a request for `email` is
granted as `https://www.googleapis.com/auth/userinfo.email`, so a connection type that
required `email` (1.0.3) refused every authorization.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# Form of each scope in Google's token response; Google OAuth2 API v2 in
# https://developers.google.com/identity/protocols/oauth2/scopes
GRANTED_FORM = {
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/adwords",
}
# Short names Google accepts in a request but grants under another name.
REQUEST_ALIASES = {"email", "profile"}


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def connection_scopes():
    (connection,) = load("contracts/connection_types.yaml")["connection_types"]
    return connection["auth"]["scopes"]["required"]


def test_connection_requires_scopes_in_the_form_google_grants():
    required = connection_scopes()
    assert set(required) == GRANTED_FORM
    assert not set(required) & REQUEST_ALIASES


def test_operations_require_only_scopes_the_connection_requests():
    requested = set(connection_scopes())
    for operation in load("contracts/operation_manifest.yaml")["operations"]:
        scopes = set(operation["required_oauth_scopes"])
        assert scopes <= requested, operation["operation_id"]
        assert not scopes & REQUEST_ALIASES, operation["operation_id"]
