"""Bundle-local closed schemas, shared by every runtime entry path."""

from functools import lru_cache
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from .errors import AdsError

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=96)
def validator(kind: str, operation: str) -> Draft202012Validator:
    path = ROOT / "schemas" / kind / f"{operation}.schema.yaml"
    return Draft202012Validator(yaml.safe_load(path.read_text(encoding="utf-8")))


def validate(kind: str, operation: str, value: object) -> None:
    if next(validator(kind, operation).iter_errors(value), None) is not None:
        code = "invalid_payload" if kind == "inputs" else "provider_unavailable"
        raise AdsError(
            code,
            "The input violates the operation contract."
            if kind == "inputs"
            else "The provider result could not be represented safely.",
        )

    _int64_money(value, kind)


def operations() -> frozenset[str]:
    return frozenset(
        p.name.removesuffix(".schema.yaml") for p in (ROOT / "schemas/inputs").glob("*.schema.yaml")
    )


def _int64_money(value: object, kind: str) -> None:
    if isinstance(value, dict):
        for name, child in value.items():
            if (
                name.endswith("_micros")
                and name not in {"average_cpc_micros", "cpa_micros"}
                and isinstance(child, str)
                and child.isascii()
                and child.isdigit()
                and int(child) > 9223372036854775807
            ):
                raise AdsError(
                    "validation_failed" if kind == "inputs" else "provider_unavailable",
                    "A monetary value exceeds the signed int64 range.",
                )
            _int64_money(child, kind)
    elif isinstance(value, list):
        for child in value:
            _int64_money(child, kind)
