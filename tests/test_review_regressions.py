"""Consolidated final-review reproduction: every case executes before assertions."""

from pathlib import Path
import yaml
from test_boundary import fixture
from test_reads import Provider
from test_mutations import Mutator
from test_reports import Reports

ROOT = Path(__file__).resolve().parents[1]


def test_final_review_behavior_regressions():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply
    from google_ads.errors import AdsError

    failures = []

    def check(name, condition, value):
        if not condition:
            failures.append((name, value))

    class Discovery(Provider):
        def __call__(self, req):
            if req.url.endswith("customers:listAccessibleCustomers"):
                return Reply({"resourceNames": ["customers/1234567890", "customers/1111111111"]})
            if "/1111111111/" in req.url:
                raise AdsError("account_access_lost", "Synthetic inaccessible account")
            return super().__call__(req)

    result = dispatch(fixture("list_accessible_accounts"), transport=Discovery())
    items = result.get("result", {}).get("items", [])
    check(
        "mixed_success_discovery",
        result.get("ok") is True
        and len(items) == 2
        and items[1]["metadata_error"]["code"] == "account_access_lost",
        result,
    )

    class Empty(Provider):
        def __call__(self, req):
            if req.url.endswith("customers:listAccessibleCustomers"):
                return Reply({})
            return super().__call__(req)

    result = dispatch(fixture("list_accessible_accounts"), transport=Empty())
    check("empty_discovery", result.get("ok") is True and result["result"]["items"] == [], result)

    class Removed(Provider):
        def __call__(self, req):
            query = (req.body or {}).get("query", "")
            if "FROM campaign_criterion " in query:
                row = {
                    "campaignCriterion": {
                        "resourceName": "customers/1234567890/campaignCriteria/1001~9999",
                        "status": "REMOVED",
                        "adSchedule": {"dayOfWeek": "MONDAY", "endHour": 1},
                    }
                }
                # Real Google honors this condition; absence means removed entities remain in reads.
                return Reply(
                    {"results": [] if "campaign_criterion.status != 'REMOVED'" in query else [row]}
                )
            return super().__call__(req)

    result = dispatch(fixture("list_targeting"), transport=Removed())
    check(
        "removed_schedule_read",
        result.get("ok") is True and result["result"]["items"] == [],
        result,
    )

    class Named(Mutator):
        def __init__(self):
            super().__init__()
            self.campaign["name"] = "customers/example"

    result = dispatch(fixture("get_campaign"), transport=Named())
    check("arbitrary_campaign_name", result.get("ok") is True, result)
    provider = Reports()
    provider.rows[0]["searchTermView"]["searchTerm"] = "customers/example"
    request = fixture("get_performance_report")
    request["action"]["input"].update(
        report_type="search_term", dimensions=["campaign", "ad_group", "search_term"]
    )
    result = dispatch(request, transport=provider)
    check("arbitrary_search_term", result.get("ok") is True, result)

    class OmittedFalse(Mutator):
        def __call__(self, req):
            reply = super().__call__(req)
            if req.write:
                for result in reply.body["mutateOperationResponses"]:
                    setting = (
                        result.get("campaignResult", {})
                        .get("campaign", {})
                        .get("networkSettings", {})
                    )
                    for key in list(setting):
                        if setting[key] is False:
                            setting.pop(key)
            return reply

    request = fixture("update_campaign")
    request["action"]["input"]["patch"] = {
        "network_settings": {
            "target_google_search": True,
            "target_search_network": False,
            "target_content_network": False,
        }
    }
    result = dispatch(request, transport=OmittedFalse())
    check("mutable_network_readback", result.get("ok") is True, result)
    page = yaml.safe_load((ROOT / "ui/pages/setup.yaml").read_text())
    form = next(c for c in page["components"] if c["component_id"] == "select_ads_customer")
    exposed = {a.get("action_id") for a in form.get("ui_schema", {}).get("actions", {}).values()}
    check(
        "native_discovery_reachable",
        {"list_accessible_accounts", "list_manager_clients"} <= exposed,
        sorted(exposed),
    )
    targeting = ROOT / "artifacts/workflows/google_ads_targeting_with_approval.yaml"
    check("targeting_review_template", targeting.is_file(), str(targeting))
    assert failures == [], "Failed review cases: " + ", ".join(name for name, _ in failures)
