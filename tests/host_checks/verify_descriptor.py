"""Verify the actual host install boundary; run inside the target fs-audit image."""

from pathlib import Path


def main():
    # Core is a test harness dependency only, never an extension runtime dependency.
    from core.application.extensions.descriptor_bundle_runtime import descriptor_with_bundle_runtime
    from core.application.extensions.lifecycle import validate_extension_descriptor_file
    from core.application.extensions.extension_contract_v2 import validate_extension_contract_v2
    from core.application.extensions.oauth_release_upgrade import resolve_oauth_release_contract
    from core.application.extensions.oauth_contract import compile_oauth_providers
    from core.infrastructure.extension_runtime.extension_runtime import compile_extension_bundle

    root = Path(__file__).resolve().parents[2]
    descriptor = root / "extension-descriptor.yaml"
    validated = validate_extension_descriptor_file(descriptor)
    assert validated["valid"], validated.get("errors")
    persisted, errors = descriptor_with_bundle_runtime(
        descriptor_path=descriptor,
        normalized_descriptor=validated["normalized"],
    )
    assert not errors, errors
    compiled = compile_extension_bundle(root, logical_bundle_dir_name="flowsteward_google_ads")
    assert compiled["status"] == "valid", compiled
    for contract in (persisted, compiled["compiled_manifest"]):
        # Installed OAuth services compile raw provider declarations, not file refs.
        assert [p.provider_id for p in compile_oauth_providers(contract)] == ["google_ads_oauth"]
    runtime_contract = validate_extension_contract_v2(persisted, bundle_root=root)
    assert runtime_contract["valid"], runtime_contract.get("errors")
    assert [
        p["provider_id"] for p in runtime_contract["normalized_contract"]["oauth_providers"]
    ] == ["google_ads_oauth"]
    assert [
        p["provider_id"] for p in resolve_oauth_release_contract(persisted)["oauth_providers"]
    ] == ["google_ads_oauth"]
    assert any(c["callback_id"] == "oauth_authorization" for c in persisted["callbacks"])
    assert len(persisted["action_definitions"]) == 26
    assert persisted["connection_types"][0]["connection_type_id"] == "google_ads_account"
    assert len(persisted["artifacts"]["workflows"]) == 28
    print("PASS: install descriptor preserves OAuth, connection, 26 actions and 28 workflows")


if __name__ == "__main__":
    main()
