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


def operations() -> frozenset[str]:
    return frozenset(
        p.name.removesuffix(".schema.yaml") for p in (ROOT / "schemas/inputs").glob("*.schema.yaml")
    )
