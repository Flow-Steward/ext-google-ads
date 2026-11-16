"""Validate the host envelope before resource lookup or provider I/O."""

from dataclasses import dataclass, field
import re
import time
from flowsteward_extension_sdk import connection_from_payload, runtime_context_from_payload
from .errors import AdsError
from .contracts import operations, validate

WRITES = frozenset(
    {
        "create_search_campaign",
        "update_campaign",
        "update_campaign_budget",
        "update_bidding",
        "create_ad_group",
        "update_ad_group",
        "create_responsive_search_ad",
        "update_responsive_search_ad",
        "set_delivery_status",
        "upsert_keywords",
        "remove_keywords",
        "upsert_negative_keywords",
        "set_campaign_targeting",
    }
)
DISCOVERY = frozenset(
    {"verify_google_identity", "list_accessible_accounts", "list_manager_clients"}
)


@dataclass
class Context:
    operation: str
    values: dict
    connection_id: str
    customer: str
    manager: str
    token: str = field(repr=False)
    account_id: str = ""
    project_id: str = ""
    revision: int = 0
    deadline: float = field(default_factory=lambda: time.monotonic() + 20.0)
    effect_status: str = "not_sent"


def from_payload(payload: dict) -> Context:
    try:
        scope = runtime_context_from_payload(payload)
    except (ValueError, TypeError):
        raise AdsError(
            "invalid_host_envelope", "A valid host execution envelope is required."
        ) from None
    if not scope.account_id or not scope.project_id:
        raise AdsError("invalid_host_envelope", "Account and project scope are required.")
    action = payload.get("action")
    if payload.get("mode") != "action" or not isinstance(action, dict):
        raise AdsError("invalid_payload", "A named action is required.")
    context = action.get("context", {})
    if not isinstance(context, dict) or (
        context.get("project_id") is not None and context["project_id"] != scope.project_id
    ):
        raise AdsError("invalid_host_envelope", "The action project differs from its host scope.")
    operation = action.get("action_id")
    if not isinstance(operation, str) or operation not in operations():
        raise AdsError("invalid_payload", "Unknown Google Ads operation.")
    values = action.get("input", {})
    validate("inputs", operation, values)
    if operation in WRITES and not isinstance(scope.raw.get("external_effect_id"), str):
        raise AdsError(
            "external_effect_claim_required", "A host external-effect claim is required."
        )
    if operation in WRITES and not scope.raw["external_effect_id"].strip():
        raise AdsError(
            "external_effect_claim_required", "A host external-effect claim is required."
        )
    connection = connection_from_payload(payload)
    if connection is None:
        raise AdsError("invalid_connection", "Select a project Google Ads connection.")
    identity = operation == "verify_google_identity"
    if not identity and connection.connection_type != "google_ads_account":
        raise AdsError("invalid_connection", "A Google Ads connection is required.")
    token = connection.secrets.get("access_token")
    oauth = connection.config.get("oauth", {})
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 8192
        or any(ord(c) < 32 for c in token)
    ):
        raise AdsError("authorization_required", "Reconnect the selected Google account.")
    if not identity and (
        not isinstance(oauth, dict) or oauth.get("lifecycle_status") != "connected"
    ):
        raise AdsError("authorization_required", "Authorize the selected Google account first.")
    customer = connection.config.get("customer_id", "")
    manager = connection.config.get("login_customer_id", "")
    if manager and (not isinstance(manager, str) or not re.fullmatch(r"[0-9]{10}", manager)):
        raise AdsError("invalid_connection", "The manager ID must contain ten digits.")
    if operation not in DISCOVERY and (
        not isinstance(customer, str) or not re.fullmatch(r"[0-9]{10}", customer)
    ):
        raise AdsError(
            "account_not_bound", "Save the target customer and check this connection first."
        )
    if any(
        key in values and values[key] != actual
        for key, actual in (
            ("expected_customer_id", customer),
            ("expected_login_customer_id", manager),
        )
    ):
        raise AdsError(
            "state_conflict", "The connection account changed; review the saved workflow inputs."
        )
    return Context(
        operation,
        values,
        connection.connection_id,
        customer,
        manager,
        token,
        scope.account_id,
        scope.project_id,
        connection.credential_revision,
    )
