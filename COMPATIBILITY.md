# Compatibility and accepted limitations

Target Flow Steward 0.9.18 commit `54a43366bf404d31c163c269af639de789b9dce6`; host1.9.0; SDK0.5.0. No core changes. Original approved revision6 requirements are retained in the task's ignored authoring evidence; implementation corrections below affect only this repository.

| Area | Implementation / evidence boundary |
| --- | --- |
| Project OAuth | Native provider settings and per-project connections; SDK `connection_from_payload` consumes host-resolved named-action target. Extension stores no token pool or OAuth broker. |
| G1 | Unfinished OAuth-less form records may exist; all Ads operations refuse until connected/bound. |
| G2 | Accepted native Save/refresh race. Flow Steward 0.9.18 already contains a separate generic config CAS; it is deliberately unused and does not fix this native Save path. No config-write mutation grant. |
| G3 | Adapter currently uses a conservative20-second deadline. Installed effective stdout/result/HTTP/caller limits, browser and live evidence remain required. Local tests are not substitutes. |
| G4/G5 | Native Setup/Help and ordinary resource-name/action inputs; no mandatory dependent selectors or custom React UI. |
| Writes | Named actions/Extension tools with trusted host external_effect_id;13 declared effects, Test Run suppression, one atomic batch, no automatic write retry. Host owns dedup/recovery. |
| Agent discovery | Contract v2 grounding advertises workflow operations. This is distinct from executable direct tools. |
| Direct read tools | Flow Steward's raw `invoke_manifest_tool` path calls `run_extension_invocation` without the named-action connection/OAuth hydration. Public SDK has no independent OAuth token resolver for this path. No direct raw tools are exported. The user accepted callable read/validate/report workflows for V1; those use named actions with ordinary project connection slots. Installed execution evidence remains pending. |
| Read retries | Up to3 attempts within one shared deadline; Retry-After respected; permanent quota/policy/precision/access failures are not retried. |
| Portable wheels |11 hash-locked packages, CPython3.12 Linux AMD64 and ARM64 wheel coverage. Architecture coverage is not installed verification on both architectures. |

## Contract corrections found by execution

- `mutates_platform` is false for Ads actions; these mutate an external service, whose effects remain separately declared.
- UI manifest pages use objects with relative `ref`, as the actual target compiler requires.
- Strategy masks select documented leaves: `manual_cpc.enhanced_cpc_enabled`, `target_spend.cpc_bid_ceiling_micros`, `maximize_conversions.target_cpa_micros`. Parent message masks from the initial candidate examples were invalid.
- Expected/previous/current geo snapshots can be empty, representing an existing all-locations state. Desired geo remains nonempty; this does not add reset-to-all geo functionality.
- ProtoJSON omitted false/zero fields are handled as defaults for unshared budgets and schedules. Mutable responses do not guarantee immutable/output-only fields; strategy/policy state is re-read where needed.

## Host source references

All references below are fixed to the target commit, not a moving branch:

- [Raw agent tool invocation](https://github.com/Flow-Steward/flow-steward-app/blob/54a43366bf404d31c163c269af639de789b9dce6/core/application/orchestration/tools/tool_resolver.py)
- [Named-action entrypoints/resources](https://github.com/Flow-Steward/flow-steward-app/blob/54a43366bf404d31c163c269af639de789b9dce6/core/infrastructure/extension_runtime/extension_runtime_entrypoints.py)
- [Contract v2 workflow grounding](https://github.com/Flow-Steward/flow-steward-app/blob/54a43366bf404d31c163c269af639de789b9dce6/core/application/extensions/extension_projection_v2.py)
- [Existing config mutation/CAS](https://github.com/Flow-Steward/flow-steward-app/blob/54a43366bf404d31c163c269af639de789b9dce6/core/application/extensions/connection_config_mutation.py)
- [Project connection slots](https://github.com/Flow-Steward/flow-steward-app/blob/54a43366bf404d31c163c269af639de789b9dce6/core/application/workflows/workflow_connection_slots.py)

Read workflow wrappers have explicit initial/continuation and scope/filter variants so absent optional inputs are not mapped to null. The targeting approval workflow verifies supplied retained expected state against a fresh complete read, computes/saves the exact managed diff using the existing Template step, then submits the same retained input after approval. It refuses an incomplete single-page snapshot. No preview action or JSON parser service was introduced.
