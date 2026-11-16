"""Safe failures with external-effect truth independent of provider text."""

from __future__ import annotations


class AdsError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        unknown: bool = False,
        restart: bool = False,
        no_effect: bool = False,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable and not unknown
        self.unknown = unknown
        self.restart = restart
        self.no_effect = no_effect
        self.retry_after = retry_after
        self.request_id = None
        self.provider_error_code = None

    def envelope(self) -> dict:
        value = {
            "ok": False,
            "result": {},
            "error_code": self.code,
            "error": self.message,
            "errors": [{"code": self.code, "message": self.message}],
            "retryable": self.retryable,
        }
        if self.request_id:
            value["request_id"] = self.request_id
        if self.provider_error_code:
            value["provider_error_code"] = self.provider_error_code
        if self.unknown:
            value.update(
                external_effect_status="timeout_unknown", definitely_no_external_effect=False
            )
        if self.no_effect:
            value["definitely_no_external_effect"] = True
        if self.restart:
            value["restart_required"] = True
        return value
