"""Managed targeting diffs never mutate language or unrelated criteria."""

from copy import deepcopy
from pathlib import Path
import yaml
from test_boundary import fixture
from test_mutations import Mutator
from test_reads import GEO_ROW


class Targets(Mutator):
    def __init__(self):
        super().__init__()
        self.criteria = [
            deepcopy(GEO_ROW),
            {
                "campaignCriterion": {
                    "resourceName": "customers/1234567890/campaignCriteria/1001~6002",
                    "type": "LANGUAGE",
                    "language": {"languageConstant": "languageConstants/1000"},
                    "status": "ENABLED",
                }
            },
        ]
        self.change_after_preflight = False
        self.criterion_reads = 0

    def __call__(self, req):
        from google_ads.transport import Reply

        query = (req.body or {}).get("query", "")
        if "FROM campaign_criterion " in query:
            self.criterion_reads += 1
            if self.change_after_preflight and self.criterion_reads > 1:
                self.campaign["geoTargetTypeSetting"]["positiveGeoTargetType"] = "PRESENCE"
            return Reply({"results": deepcopy(self.criteria)})
        if req.url.endswith("googleAds:mutate") and any(
            "campaignCriterionOperation" in o for o in req.body["mutateOperations"]
        ):
            self.writes.append(req)
            if self.timeout:
                raise TimeoutError("private")
            values = []
            for operation in req.body["mutateOperations"]:
                body = operation["campaignCriterionOperation"]
                if "remove" in body:
                    name = body["remove"]
                    for row in self.criteria:
                        if row["campaignCriterion"]["resourceName"] == name:
                            row["campaignCriterion"]["status"] = "REMOVED"
                    result = {"resourceName": name}
                else:
                    entity = deepcopy(body["create"])
                    entity.update(
                        resourceName=f"customers/1234567890/campaignCriteria/1001~{7000 + len(self.criteria)}",
                        status="ENABLED",
                    )
                    entity["type"] = "LOCATION" if "location" in entity else "AD_SCHEDULE"
                    self.criteria.append({"campaignCriterion": entity})
                    result = {
                        "resourceName": entity["resourceName"],
                        "campaignCriterion": deepcopy(entity),
                    }
                values.append({"campaignCriterionResult": result})
            return Reply({"mutateOperationResponses": values}, "synthetic-google-request-001")
        return super().__call__(req)


def test_location_patch_exact_result_and_leaf_mask():
    from google_ads.runtime import dispatch

    provider = Targets()
    response = dispatch(fixture("set_campaign_targeting"), transport=provider)
    expected = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "examples/set_campaign_targeting.yaml").read_text()
    )["success"]["response"]
    assert response == expected
    op = provider.writes[0].body["mutateOperations"][0]["campaignOperation"]
    assert op["updateMask"] == "geo_target_type_setting.positive_geo_target_type"


def test_expected_families_must_match_desired_families_and_current_state():
    from google_ads.runtime import dispatch

    provider = Targets()
    p = fixture("set_campaign_targeting")
    p["action"]["input"]["expected_current"] = {"geo_target_constants": ["geoTargetConstants/2440"]}
    assert dispatch(p, transport=provider)["error_code"] == "validation_failed"
    p = fixture("set_campaign_targeting")
    p["action"]["input"]["expected_current"]["location_options"]["positive_geo_target_type"] = (
        "PRESENCE_OR_INTEREST"
    )
    assert dispatch(p, transport=provider)["error_code"] == "state_conflict"
    assert not provider.writes


def test_geo_replacement_is_atomic_remove_add_and_preserves_language():
    from google_ads.runtime import dispatch

    provider = Targets()
    p = fixture("set_campaign_targeting")
    p["action"]["input"].update(
        expected_current={"geo_target_constants": ["geoTargetConstants/2440"]},
        desired={"geo_target_constants": ["geoTargetConstants/2840"]},
    )
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    operations = provider.writes[0].body["mutateOperations"]
    assert len(operations) == 2 and "remove" in operations[0]["campaignCriterionOperation"]
    assert operations[1]["campaignCriterionOperation"]["create"]["location"] == {
        "geoTargetConstant": "geoTargetConstants/2840"
    }
    assert provider.criteria[1]["campaignCriterion"]["status"] == "ENABLED"
    assert response["result"]["current"]["geo_target_constants"] == ["geoTargetConstants/2840"]
    assert response["result"]["preflight_is_provider_cas"] is False


def test_weekly_schedule_uses_remove_add_and_reset_all_time():
    from google_ads.runtime import dispatch

    provider = Targets()
    p = fixture("set_campaign_targeting")
    weekly = {
        "mode": "weekly",
        "intervals": [
            {"day": "MONDAY", "start_hour": 9, "start_minute": 0, "end_hour": 17, "end_minute": 30}
        ],
    }
    p["action"]["input"].update(
        expected_current={"schedule": {"mode": "all_time"}}, desired={"schedule": weekly}
    )
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    create = provider.writes[0].body["mutateOperations"][0]["campaignCriterionOperation"]["create"]
    assert create["adSchedule"]["endMinute"] == "THIRTY"
    p["action"]["input"].update(
        expected_current={"schedule": weekly}, desired={"schedule": {"mode": "all_time"}}
    )
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    assert response["result"]["current"]["schedule"] == {"mode": "all_time"}
    assert all(
        "update" not in o["campaignCriterionOperation"]
        for o in provider.writes[-1].body["mutateOperations"]
    )


def test_targeting_noop_never_mutates():
    from google_ads.runtime import dispatch

    provider = Targets()
    p = fixture("set_campaign_targeting")
    p["action"]["input"]["desired"] = deepcopy(p["action"]["input"]["expected_current"])
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    assert response["result"]["mutation_operation_count"] == 0
    assert not provider.writes


def test_targeting_timeout_never_retries():
    from google_ads.runtime import dispatch

    provider = Targets()
    provider.timeout = True
    response = dispatch(fixture("set_campaign_targeting"), transport=provider)
    assert response["error_code"] == "outcome_unknown"
    assert len(provider.writes) == 1
