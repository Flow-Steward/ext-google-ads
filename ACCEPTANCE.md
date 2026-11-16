# Acceptance evidence boundaries

This matrix tracks revision6 AC01–AC24. **No AC requiring installed, browser or live evidence is marked passed by local tests.** Final fix-pass synthetic suite:238 passed under the exact Flow Steward 0.9.18 Docker extension gate; compile/ruff/mypy/Bandit and manifest/UI/schema validation passed after the single final review fix pass. The fresh review inspected de93544; its material findings were fixed with regression evidence, and the user-approved callable read alternative was added afterward. Final committed-state evidence is delivered separately with the extension SHA and bundle hashes.

| ID | Local evidence | Remaining acceptance |
| --- | --- | --- |
| AC01 | Boundary/target fixtures; separate workflow slots | Installed two-account isolation |
| AC02 | Project-context/ref mismatches rejected | Host RBAC/cross-project integration |
| AC03 | Direct/nested MCC, cycle/inaccessible/limits fixtures | Live accessible hierarchy |
| AC04 | Account/discovery/bind metadata fixtures | Real MCC route/access failures |
| AC05 | Closed inputs, resource prefixes, expected customer/MCC checks | Host sequential connection change |
| AC06 | Two native forms, incomplete OAuth refusal, read-only bind | Browser Save/revision/session behavior |
| AC07 | Atomic create wire/status/mapping fixtures | Authorized live paused creation with two groups |
| AC08 | Expanded/byte bounds, atomic flags, rejection/error fixtures | Provider transaction behavior in live test account |
| AC09 | Standalone mutation/RSA/keyword/targeting contract tests | Live mutable/provider constraints |
| AC10 | No-claim/input forgery/alias refusal; selected-only status wire | Valid installed host authority/effect path |
| AC11 | Unshared budget/user/currency/strategy/conflict fixtures | Google currency increments and live budget |
| AC12 | Unknown write no-retry; business keyword dedup | Host same-intent replay/conflict and direct Idempotency-Key |
| AC13 | Write suppression and validate-only wire fixtures | Installed host Test Run/config unchanged |
| AC14 | All24 report layouts, Decimal/int64/rows/bytes; lossless cursor fixtures | Installed G3 deadline/cap behavior |
| AC15 | Two-slot draft report workflow, scoped result identity | Two-client installed run/error routing |
| AC16 | Provider enum taxonomy, quota/rate/retry/cursor/policy fixtures | Live access/revocation responses |
| AC17 | Native metadata compiler/UI checks | Entire browser acceptance pending |
| AC18 | 26 IDs/13 effects/schema examples/IO parity; no private runtime imports | Callable-workflow alternative accepted; installed agent path pending |
| AC19 | Official artwork and both-architecture hashed wheels; compiler checks | Clean bundle plus standard installation pending |
| AC20 | Synthetic tests explicitly labelled | Entire authorized test-account live acceptance pending |
| AC21 | G2/revoke documented, connection-bound adapter | Real same-subject refresh/revoke across projects |
| AC22 | Closed schemas, omission/empty/default/masks/identity/reset fixtures | Browser/workflow mappings on installed host |
| AC23 | 26 named-action handlers and explicit paths; reused host mechanisms | Direct agent reads: approved callable-workflow V1 path, installed run pending |
| AC24 | Expanded limit/schedule/RSA/REMOVED/unknown/language/input-output/deadline/type fixtures | Installed effective limits and representative live constraints |

## Operation-to-contract tests

Every operation also has a closed input/result/response schema and synthetic example. All examples are validated by `tests/test_bundle_contract.py`. All write actions share claim/test-mode/unknown-output boundaries; actual host ledger replay is a separate integration requirement.

| Operation | Provider contract test module |
| --- | --- |
| `verify_google_identity` | `tests/test_provider.py` |
| `list_accessible_accounts` | `tests/test_reads.py` |
| `list_manager_clients` | `tests/test_reads.py` |
| `bind_ads_account` | `tests/test_provider.py` |
| `get_account` | `tests/test_provider.py` |
| `list_campaigns` | `tests/test_reads.py` |
| `get_campaign` | `tests/test_reads.py` |
| `list_ad_groups` | `tests/test_reads.py` |
| `list_ads` | `tests/test_reads.py` |
| `list_keywords` | `tests/test_reads.py` |
| `list_targeting` | `tests/test_reads.py` |
| `validate_search_campaign` | `tests/test_create.py` |
| `create_search_campaign` | `tests/test_create.py` |
| `update_campaign` | `tests/test_mutations.py` |
| `update_campaign_budget` | `tests/test_mutations.py` |
| `update_bidding` | `tests/test_mutations.py` |
| `create_ad_group` | `tests/test_mutations.py` |
| `update_ad_group` | `tests/test_mutations.py` |
| `create_responsive_search_ad` | `tests/test_rsa.py` |
| `update_responsive_search_ad` | `tests/test_rsa.py` |
| `set_delivery_status` | `tests/test_mutations.py` |
| `upsert_keywords` | `tests/test_keywords.py` |
| `remove_keywords` | `tests/test_keywords.py` |
| `upsert_negative_keywords` | `tests/test_keywords.py` |
| `set_campaign_targeting` | `tests/test_targeting.py` |
| `get_performance_report` | `tests/test_reports.py` |

## Required environment for completion

The environment owner supplies an API-enabled Cloud project, OAuth Web client/callback, permitted Google user, separate test MCC and test client with suitable roles. Test client hierarchy must be appropriate for Google's test accounts. Installation, OAuth browser flows and live Ads writes have not been performed by this development task. Production serving/spend is not an acceptance requirement and has not been authorized.

Before release, validate the approved callable agent-read path described in COMPATIBILITY.md and verify actual installed G3 stdout/result/HTTP/caller limits. Accepted G2 remains a documented residual risk, not a promise that concurrent Save/refresh is safe.
