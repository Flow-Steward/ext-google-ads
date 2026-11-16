"""Public metadata, examples and offline dependency coverage stay in sync."""

import hashlib
from pathlib import Path
import zipfile
import yaml
import pytest
from jsonschema import Draft202012Validator
from google_ads.context import WRITES
from google_ads.contracts import operations

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_all_operation_and_effect_ids_match_without_write_tools():
    manifest = load("extension.yaml")
    ops = load("contracts/operation_manifest.yaml")["operations"]
    actions = load("ui/actions/actions.yaml")["actions"]
    assert len(operations()) == 26
    assert {op["operation_id"] for op in ops} == operations() == {a["action_id"] for a in actions}
    assert {e["operation_id"] for e in manifest["external_effects"]} == WRITES
    assert len(WRITES) == 13
    assert all(a["mutates_platform"] is False for a in actions)
    assert "tool_manifest" not in manifest


@pytest.mark.parametrize("name", sorted(operations()))
def test_example_success_is_valid_for_both_result_and_response(name):
    example = load(f"examples/{name}.yaml")["success"]
    Draft202012Validator(load(f"schemas/inputs/{name}.schema.yaml")).validate(
        example["request"]["action"]["input"]
    )
    Draft202012Validator(load(f"schemas/results/{name}.schema.yaml")).validate(
        example["response"]["result"]
    )
    Draft202012Validator(load(f"schemas/responses/{name}.schema.yaml")).validate(
        example["response"]
    )


@pytest.mark.parametrize("name", sorted(operations()))
def test_public_operation_io_schemas_match_runtime_contract(name):
    op = next(
        op
        for op in load("contracts/operation_manifest.yaml")["operations"]
        if op["operation_id"] == name
    )
    for direction, kind in [("inputs", "inputs"), ("outputs", "results")]:
        schema = load(f"schemas/{kind}/{name}.schema.yaml")
        if "properties" not in schema:
            continue
        actual = {item["name"]: item.get("schema") for item in op[direction]}
        assert actual == schema["properties"]


def test_hash_locked_runtime_wheels_cover_both_linux_architectures():
    manifest = load("extension.yaml")
    assert len(manifest["python_requirements"]) == 11
    for req in manifest["python_requirements"]:
        matching = []
        for wheel in (ROOT / "wheels").glob("*.whl"):
            digest = "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
            if digest in req["hashes"]:
                matching.append(wheel)
        assert matching, req["name"]
        for architecture in ["x86_64", "aarch64"]:
            assert any(
                "none-any.whl" in path.name or architecture in path.name for path in matching
            ), req["name"]
        for wheel in matching:
            with zipfile.ZipFile(wheel) as z:
                metadata = z.read(
                    next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
                ).decode()
            assert f"Version: {req['version']}" in metadata
