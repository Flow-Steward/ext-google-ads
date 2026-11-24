# Google Ads 1.0.2

First public catalog release of the Flow Steward Google Ads integration.

- 26 named operations for Search campaigns, ad groups, responsive search ads, keywords, targeting and reports.
- Project-scoped OAuth connections and optional manager routing for agency client accounts.
- 28 workflow templates, including callable reads and explicit approval flows. New campaign, group and ad resources are PAUSED.
- Native setup, global Support page, issue templates and separate Linux AMD64/ARM64 packages.
- Includes the installation metadata and inline OAuth-provider fixes exercised on Flow Steward 0.9.18.

Installed 1.0.1 was observed active and Healthy; its OAuth configuration form and callback registration loaded. OAuth consent, real multi-account isolation, installed callable workflows, live writes and refresh/revoke acceptance remain pending. This release is unverified in the catalog. See ACCEPTANCE.md and COMPATIBILITY.md.

G2 remains: concurrent configuration Save/OAuth refresh can require reconnection. Revoking a shared Google grant may affect other connections for that Google user and Cloud project.

Maintained by Flow Steward; not an official Google product. No core changes.
