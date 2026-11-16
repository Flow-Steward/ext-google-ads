# Build and validation

Use the exact Flow Steward 0.9.18 target checkout and its disposable `fs-audit` Docker runtime. Run focused regression tests through:

```sh
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root /absolute/path/to/ext-google-ads --test-paths tests --evidence-mode off
```

Do not use host pytest or infer release evidence from a different core commit. Final evidence must name the extension commit and target commit. Hosted/heavy gates are not part of this short local extension scope.

`requirements.in` pins runtime dependencies. The target public `extensions lock-deps` CLI generated the full11-package transitive lock and both-architecture wheel hashes in `extension.yaml`. CPython3.12 manylinux2014 x86_64/aarch64 wheels run on the target Debian bookworm glibc2.36 runtime. The SDK0.5.0 wheel was built from the exact target's public SDK source (hash in manifest); that SDK version was absent from public PyPI at preparation time.

The target bundle downloader has no local find-links input for an unpublished SDK. Use the documented hash-locked pip fallback with the retained local SDK wheel:

```sh
python -m pip --isolated download --only-binary=:all: --no-deps --require-hashes --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --abi cp312 --abi abi3 --abi none --dest wheels -r requirements.runtime.lock
python -m pip --isolated download --only-binary=:all: --no-deps --require-hashes --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --abi cp312 --abi abi3 --abi none --dest wheels -r requirements.runtime.lock
```

Run from this repository root in the authoring container. Each locked dependency must have matching hashed wheels for both architectures or one universal wheel. No runtime download is permitted.

Build only from a **clean staging directory** populated from a verified committed tree. The target bundler does not exclude this repository's `.git`, authoring logs or previous distributions automatically; never point it directly at the developer checkout. Include committed runtime wheels; omit authoring-only dev wheels and evidence logs. Then run public `extensions validate` and `extensions bundle` against the staging parent. Keep archives below50MiB compressed/150MiB uncompressed and record SHA256. Bundling is not installation or publication, and no production advertising is authorized by these checks.

Before release, complete the pending installed/browser/live acceptance in ACCEPTANCE.md, validate the approved callable agent-read workflows on the installed host, verify the actual G3 limits and review the final committed state. Any live write needs a deliberately authorized test account/action path; fake-provider tests must remain labelled synthetic.

The archive installer also validates `extension-descriptor.yaml` before merging the executable bundle. Its strict artifact schema cannot declare OAuth callbacks. Keep the executable OAuth contract in `extension.yaml`; omit `runtime.extension_contract_v2` from the artifact descriptor so the standard bundle import inherits the complete contract. Duplicating its OAuth refs there makes installation fail before the merge.

Run the additional host boundary check inside the exact target audit image, with the bundle mounted read-only and the host's `/app` on `PYTHONPATH`:

```sh
PYTHONPATH=/app python /authoring/flowsteward_google_ads/tests/host_checks/verify_descriptor.py
```

This check uses core only as the external test harness. It validates the artifact descriptor and merged runtime contract, including OAuth release fingerprints, the account connection, all 26 actions and 28 workflow artifacts. Run it on the extracted archive as well; public manifest validation alone does not exercise this install boundary.
