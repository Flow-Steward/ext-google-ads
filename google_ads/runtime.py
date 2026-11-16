"""Named action dispatcher. Provider writes require the host effect boundary."""

from .context import WRITES, from_payload
from .contracts import validate
from .accounts import get_account, verify_identity
from .errors import AdsError
from .transport import PinnedTransport
from .reads import READS, handle_read
from .search_create import execute as search_create


def dispatch(payload: dict, *, transport=None) -> dict:
    ctx = None
    try:
        ctx = from_payload(payload)
        if ctx.operation in WRITES and payload["runtime_context"].get("test_mode") is True:
            return {
                "ok": True,
                "result": {
                    "test_mode_status": "suppressed",
                    "external_effect_status": "suppressed",
                    "definitely_no_external_effect": True,
                },
                "external_effect_status": "suppressed",
                "definitely_no_external_effect": True,
            }
        send = transport if transport is not None else PinnedTransport()
        if ctx.operation == "verify_google_identity":
            result = verify_identity(ctx, send)
        elif ctx.operation in {"get_account", "bind_ads_account"}:
            result = get_account(ctx, send)
        elif ctx.operation in {"create_search_campaign", "validate_search_campaign"}:
            result = search_create(ctx, send)
        elif ctx.operation in READS:
            result = handle_read(ctx, send)
        else:
            raise AdsError(
                "unsupported_configuration",
                "This operation is not implemented in the current development checkout.",
            )
        validate("results", ctx.operation, result)
        response = {"ok": True, "result": result}
        if ctx.operation in WRITES:
            response.update(external_effect_status="succeeded", definitely_no_external_effect=False)
        return response
    except AdsError as error:
        if (
            ctx is not None
            and ctx.effect_status != "not_sent"
            and not error.unknown
            and not error.no_effect
        ):
            return AdsError(
                "outcome_unknown",
                "The write result needs reconciliation; do not retry automatically.",
                unknown=True,
            ).envelope()
        response = error.envelope()
        if ctx is None or ctx.effect_status == "not_sent":
            response["definitely_no_external_effect"] = True
        return response
    except Exception:
        unknown = ctx is not None and ctx.effect_status != "not_sent"
        return AdsError(
            "outcome_unknown" if unknown else "internal_error",
            "The write outcome needs reconciliation; do not retry automatically."
            if unknown
            else "The operation could not be completed safely.",
            unknown=unknown,
        ).envelope()
