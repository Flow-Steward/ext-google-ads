# Google Ads extension

Implementation in progress for Flow Steward Pro0.9.18, host contract1.9.0, public SDK0.5.0. Search-only revision6 scope:26 actions,13 host-managed external effects. This checkout is not ready for installation or publication.

The host owns OAuth, project connections, effect claims and autonomy. Native setup may contain an unfinished OAuth-less connection; Ads actions must refuse it. Concurrent configuration Save/OAuth refresh is an accepted residual host risk (G2), not fixed here. Prefer separate client connections and finish setup before workflows. Resource names use ordinary inputs and workflow mappings, not dependent selectors.

Implementation/evidence: ignored logs/implementation-plan.md and logs/progress.md. Validation must use the exact target checkout's Docker lint.sh extension checks; no host pytest. Live/browser/G3 deployment evidence is pending. No production ad traffic is authorized by development tests.
