# Google Ads for Flow Steward

Separate out-of-process extension for **Flow Steward 0.9.18** (`54a43366bf404d31c163c269af639de789b9dce6`), host contract **1.9.0**, public SDK **0.5.0**, Google Ads REST **v26**. Implements the approved revision 6 Search scope: **26 named operations and 13 external effects**. No core patch is included.

Published as an unverified integration maintained by Flow Steward, without Google endorsement. Installation/runtime health and the OAuth setup form were checked on Flow Steward 0.9.18; OAuth consent, connected-account operations and live workflows remain unverified. See [COMPATIBILITY.md](COMPATIBILITY.md), [ACCEPTANCE.md](ACCEPTANCE.md) and [RELEASE-NOTES.md](RELEASE-NOTES.md).

## Connect an agency client

1. Enable Google Ads API in the client's selected Google Cloud project and configure a Web OAuth client. Configure the host-generated redirect URI exactly. Cloud access must permit the account type; no developer token is accepted or sent.
2. Configure OAuth Client ID/Secret in the existing project provider settings, then authorize Google from the extension's native setup page.
3. Select the newly authorized connection in the account form. Enter the **ten-digit Customer ID**, without hyphens, and optional ten-digit Manager ID for the intended MCC route. Leave Manager ID absent for direct access. Save, then run the account check.
4. Finish setup before using workflows. A form saved without a selected connection can create an unfinished OAuth-less record; advertising actions refuse it. OAuth success alone does not verify Ads customer access.
5. Create a separately named project connection for another client. Select the correct existing project connection/slot for each workflow. Write inputs also require the saved expected customer and MCC assertions; a changed binding is rejected before Google mutation.

Concurrent native Save/OAuth refresh remains accepted risk **G2**. Editing during active workflows can require reconnection; avoiding edits reduces exposure but is not a concurrency guarantee. Host CAS exists in this target but this V1 does not use it. Revoking a Google grant can affect other connections for the same Google user/Cloud project.

## Run operations

Use the standard Extension tools/named-action workflow path. Discovery and resource lists return ordinary resource names; enter them directly or map outputs from prior steps. No custom frontend, dependent selector or second connection system is required. Failed reads are explicit errors, never empty-success substitutes.

New campaign/group/ad resources are **PAUSED**; positive keywords can be ENABLED inside PAUSED parents. Creation uses one atomic expanded mutate (maximum10000 operations). Validate-only checks the same plan without effects. Budgets are explicitly unshared, DAILY average budgets, not hard daily billing caps. Money is a positive signed-int64 micros string in the account's currency; Google decides currency-specific increments without local rounding.

Only standard campaign-owned Manual CPC, Maximize Clicks and Maximize Conversions (optional target CPA) are supported for writes. Portfolio/non-Search/unsupported existing resources are refused. Keyword identity trims only outer spaces; text/match/polarity remain immutable. Negatives are ensure-present/no-op; REMOVED criteria are not revived. RSA lists replace supplied lists entirely and content editing preserves status. Managed targeting covers positive geo, location options and schedule; language and unrelated criteria are not rewritten. Expected targeting/budget checks are preflight checks, not provider CAS.

Use existing approval/manual autonomy for activation, budget/bidding, active-content/targeting changes and removal. The draft templates freeze exact inputs before approval; they do not promise cryptographic approval binding. ENABLED alone does not guarantee serving (parents, policy, billing, account state still apply). Never retry an unknown write outcome automatically; use the host's existing effect ledger/recovery and provider reconciliation. Test Run suppresses all thirteen writes.

## Included draft workflows

- `google_ads_create_paused_search`: save exact customer/specification, validate, review, then create PAUSED structure.
- `google_ads_delivery_with_approval`: review and change only one selected resource's status; parents and siblings remain untouched.
- `google_ads_targeting_with_approval`: read current targeting, verify retained expected state, compute/save a deterministic diff, review, then write the same input. A complete single page (up to1000 current criteria) is required; incomplete snapshots stop before approval. Larger snapshots require existing pagination composition before review.
- `google_ads_two_client_reports`: two independently selected project connection slots; each result retains actual customer/connection/currency identity.

Templates install disabled and must be configured for a project before enabling. They contain no account IDs or credentials. For V1 the approved agent read path uses the included `google_ads_read_*` callable workflows, whose connector steps receive the host-selected OAuth connection. Initial/continuation variants preserve paging; ad/keyword variants select campaign or ad-group scope; campaign filtered variants require both filter arrays. OAuth identity callback and account setup bind remain operator-only. Configure and enable these draft workflows in the intended project before agents use them. No raw `invoke_tool` alias is accepted, especially for writes.

## Reports and operational errors

Reports support six types and four finite layouts per type, with date/device where compatible. Dates are inclusive account-local calendar dates (maximum366 days). Counts/cost remain lossless strings; conversions/value are decimal strings. CTR is a ratio; CPC/CPA use micros; ROAS divides value in account currency by cost in currency. Derived ratios use12 fractional places, half-even, and null for zero denominators. At10000 rows or byte/deadline bounds, a result explicitly says incomplete and asks for a narrower new request. Search terms can be privacy limited and conversions can arrive later. Do not sum accounts with different currencies.

Resolve Cloud-project production-access errors in Google Cloud/Ads access settings. If Google requires an EU political advertising declaration, complete the missing declarations in Google Ads; this V1 does not patch existing declarations. Quota exhaustion, expired cursors, stale bindings, authorization loss and validation failures are distinct errors. Reconnect only through the standard host OAuth flow.

## Development

See [PUBLISHING.md](PUBLISHING.md) for exact-target Docker gates, offline wheels and clean-stage packaging. [BRANDING.md](BRANDING.md) records the unchanged official Google asset source. Synthetic envelope examples deliberately omit access tokens and do not confer host authority.

Russian locale currently translates some headings; operation names and several labels/help paragraphs use English fallback. Full Russian localization remains deferred.

## Support

[Report a problem or ask a question](https://github.com/Flow-Steward/ext-google-ads/issues/new/choose), or [browse existing issues](https://github.com/Flow-Steward/ext-google-ads/issues). Do not include credentials, tokens or customer data. Google Ads and its logo are trademarks of Google LLC.
