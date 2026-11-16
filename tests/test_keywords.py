"""Keyword business identity is independent of host effect identity."""

from copy import deepcopy
import re
import pytest
from test_boundary import fixture
from test_mutations import Mutator, merge
from test_reads import CAMPAIGN, KEYWORD_ROW


class Keywords(Mutator):
    def __init__(self):
        super().__init__()
        self.criteria = []
        self.malformed = False

    def __call__(self, req):
        from google_ads.transport import Reply

        query = (req.body or {}).get("query", "")
        if req.url.endswith("googleAds:mutate") and any(
            "CriterionOperation" in next(iter(o)) for o in req.body["mutateOperations"]
        ):
            self.writes.append(req)
            if self.timeout:
                raise TimeoutError("provider private")
            result = []
            for operation in req.body["mutateOperations"]:
                kind = next(iter(operation))
                body = operation[kind]
                entity = (
                    "adGroupCriterion"
                    if kind == "adGroupCriterionOperation"
                    else "campaignCriterion"
                )
                if "create" in body:
                    value = deepcopy(body["create"])
                    collection = (
                        "adGroupCriteria" if entity == "adGroupCriterion" else "campaignCriteria"
                    )
                    parent = "2001" if entity == "adGroupCriterion" else "1001"
                    suffix = 4001 + len(self.criteria)
                    value["resourceName"] = f"customers/1234567890/{collection}/{parent}~{suffix}"
                    if entity == "campaignCriterion":
                        value["status"] = "ENABLED"
                    self.criteria.append({"campaign": {"resourceName": CAMPAIGN}, entity: value})
                else:
                    name = body.get("remove") or body["update"]["resourceName"]
                    value = next(
                        r[entity]
                        for r in self.criteria
                        if entity in r and r[entity]["resourceName"] == name
                    )
                    if "remove" in body:
                        value["status"] = "REMOVED"
                    else:
                        merge(value, body["update"])
                result.append(
                    {
                        entity + "Result": {
                            "resourceName": value["resourceName"],
                            **({entity: deepcopy(value)} if "remove" not in body else {}),
                        }
                    }
                )
            if self.malformed:
                result = []
            return Reply({"mutateOperationResponses": result}, "synthetic-google-request-001")
        if "FROM ad_group_criterion " in query or "FROM campaign_criterion " in query:
            entity = (
                "adGroupCriterion" if "FROM ad_group_criterion " in query else "campaignCriterion"
            )
            rows = [deepcopy(r) for r in self.criteria if entity in r]
            match = re.search(
                r"(?:ad_group_criterion|campaign_criterion)\.resource_name = '([^']+)'", query
            )
            if match:
                rows = [r for r in rows if r[entity]["resourceName"] == match.group(1)]
            return Reply({"results": rows})
        return super().__call__(req)


@pytest.mark.parametrize("name", ["upsert_keywords", "upsert_negative_keywords"])
def test_ensure_present_is_noop_even_under_new_host_intent(name):
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture(name)
    first = dispatch(p, transport=provider)
    assert first["ok"], first
    p["runtime_context"]["external_effect_id"] = "a_different_host_intent"
    second = dispatch(p, transport=provider)
    assert second["ok"], second
    assert second["result"]["mutation_operation_count"] == 0
    assert second["result"]["items"][0]["outcome"] == "UNCHANGED"
    assert len(provider.writes) == 1
    assert (
        first["result"]["items"][0]["criterion_resource_name"]
        == second["result"]["items"][0]["criterion_resource_name"]
    )


def test_positive_updates_only_status_and_bid_with_exact_masks():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("upsert_keywords")
    assert dispatch(p, transport=provider)["ok"]
    p["action"]["input"]["keywords"][0].update(status="PAUSED", cpc_bid_micros="2000000")
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    operation = provider.writes[-1].body["mutateOperations"][0]["adGroupCriterionOperation"]
    assert operation["updateMask"] == "status,cpc_bid_micros"
    assert set(operation["update"]) == {"resourceName", "status", "cpcBidMicros"}
    assert response["result"]["items"][0]["outcome"] == "UPDATED"


def test_duplicate_input_identity_after_outer_trim_rejected():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("upsert_keywords")
    value = deepcopy(p["action"]["input"]["keywords"][0])
    value["text"] = "  " + value["text"] + " "
    p["action"]["input"]["keywords"].append(value)
    response = dispatch(p, transport=provider)
    assert response["error_code"] == "validation_failed"
    assert not provider.writes


def test_identity_preserves_case_unicode_and_internal_spacing():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("upsert_keywords")
    values = ["Case", "case", "ca  se", "café", "café"]
    p["action"]["input"]["keywords"] = [
        {"text": v, "match_type": "EXACT", "status": "ENABLED"} for v in values
    ]
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    assert [i["text"] for i in response["result"]["items"]] == values
    assert len(provider.writes[0].body["mutateOperations"]) == 5


def test_multiple_provider_matches_fail_without_selecting_one():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("upsert_keywords")
    assert dispatch(p, transport=provider)["ok"]
    extra = deepcopy(provider.criteria[0])
    extra["adGroupCriterion"]["resourceName"] = "customers/1234567890/adGroupCriteria/2001~9999"
    provider.criteria.append(extra)
    response = dispatch(p, transport=provider)
    assert response["error_code"] == "state_conflict"
    assert len(provider.writes) == 1


def test_removed_keyword_not_revived_and_repeated_remove_is_noop():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("upsert_keywords")
    first = dispatch(p, transport=provider)
    assert first["ok"], first
    remove = fixture("remove_keywords")
    response = dispatch(remove, transport=provider)
    assert response["ok"], response
    assert response["result"]["items"][0]["outcome"] == "REMOVED"
    response = dispatch(remove, transport=provider)
    assert response["ok"], response
    assert response["result"]["mutation_operation_count"] == 0
    assert response["result"]["items"][0]["outcome"] == "ALREADY_REMOVED"
    recreated = dispatch(p, transport=provider)
    assert recreated["ok"], recreated
    assert (
        recreated["result"]["items"][0]["criterion_resource_name"]
        != first["result"]["items"][0]["criterion_resource_name"]
    )


def test_unknown_remove_and_nonkeyword_criterion_are_errors():
    from google_ads.runtime import dispatch

    provider = Keywords()
    p = fixture("remove_keywords")
    assert dispatch(p, transport=provider)["error_code"] == "resource_not_found"
    row = deepcopy(KEYWORD_ROW)
    row["adGroupCriterion"].pop("keyword")
    row["adGroupCriterion"]["location"] = {"geoTargetConstant": "geoTargetConstants/2440"}
    provider.criteria = [row]
    assert dispatch(p, transport=provider)["error_code"] == "unsupported_configuration"
    assert not provider.writes


@pytest.mark.parametrize("name", ["upsert_keywords", "upsert_negative_keywords", "remove_keywords"])
def test_keyword_write_timeout_never_retries(name):
    from google_ads.runtime import dispatch

    provider = Keywords()
    provider.timeout = True
    if name == "remove_keywords":
        provider.criteria = [deepcopy(KEYWORD_ROW)]
    response = dispatch(fixture(name), transport=provider)
    assert response["error_code"] == "outcome_unknown"
    assert response["definitely_no_external_effect"] is False
    assert len(provider.writes) == 1
