"""Standalone campaign/group/status effects preserve ownership and exact masks."""

from copy import deepcopy
from pathlib import Path
import yaml
import pytest
from test_boundary import fixture
from test_reads import Provider, CAMPAIGN_ROW, GROUP_ROW, AD_ROW

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    "update_campaign",
    "update_campaign_budget",
    "update_bidding",
    "create_ad_group",
    "update_ad_group",
    "set_delivery_status",
]


def merge(old, new):
    for key, value in new.items():
        if isinstance(value, dict) and isinstance(old.get(key), dict):
            merge(old[key], value)
        else:
            old[key] = deepcopy(value)


class Mutator(Provider):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.timeout = False
        self.two_budget_users = False
        self.campaign = deepcopy(CAMPAIGN_ROW["campaign"])
        self.campaign["campaignBudget"] = "customers/1234567890/campaignBudgets/9001"
        self.budget = {
            "resourceName": self.campaign["campaignBudget"],
            "amountMicros": "20000000",
            "explicitlyShared": False,
            "period": "DAILY",
        }
        self.group = deepcopy(GROUP_ROW["adGroup"])
        self.group.update(name="Brand", cpcBidMicros="1500000")
        self.ad_group_ad = deepcopy(AD_ROW["adGroupAd"])
        self.ad_group_ad["policySummary"]["reviewStatus"] = "REVIEW_IN_PROGRESS"

    def __call__(self, req):
        from google_ads.transport import Reply

        query = (req.body or {}).get("query", "")
        if req.url.endswith("googleAds:mutate"):
            self.writes.append(req)
            if self.timeout:
                raise TimeoutError("sensitive transport failure")
            results = []
            for operation in req.body["mutateOperations"]:
                kind = next(iter(operation))
                body = operation[kind]
                entities = {
                    "campaignOperation": ("campaignResult", "campaign", self.campaign),
                    "campaignBudgetOperation": (
                        "campaignBudgetResult",
                        "campaignBudget",
                        self.budget,
                    ),
                    "adGroupOperation": ("adGroupResult", "adGroup", self.group),
                    "adGroupAdOperation": ("adGroupAdResult", "adGroupAd", self.ad_group_ad),
                }
                result_key, entity_name, state = entities[kind]
                value = body.get("update", body.get("create", {}))
                merge(state, value)
                if kind == "adGroupOperation" and "create" in body:
                    state["resourceName"] = "customers/1234567890/adGroups/2001"
                if kind == "campaignOperation":
                    for field, enum in [
                        ("manualCpc", "MANUAL_CPC"),
                        ("targetSpend", "TARGET_SPEND"),
                        ("maximizeConversions", "MAXIMIZE_CONVERSIONS"),
                    ]:
                        if field in value:
                            state["biddingStrategyType"] = enum
                            for other in ["manualCpc", "targetSpend", "maximizeConversions"]:
                                if other != field:
                                    state.pop(other, None)
                results.append(
                    {
                        result_key: {
                            "resourceName": state["resourceName"],
                            entity_name: deepcopy(state),
                        }
                    }
                )
            return Reply({"mutateOperationResponses": results}, "synthetic-google-request-001")
        if "FROM campaign_budget " in query:
            return Reply({"results": [{"campaignBudget": deepcopy(self.budget)}]})
        if "FROM campaign " in query:
            rows = [{"campaign": deepcopy(self.campaign), "campaignBudget": deepcopy(self.budget)}]
            if self.two_budget_users and "campaign.campaign_budget =" in query:
                extra = deepcopy(rows[0])
                extra["campaign"]["resourceName"] = "customers/1234567890/campaigns/1002"
                rows.append(extra)
            return Reply({"results": rows})
        if "FROM ad_group_ad " in query:
            return Reply(
                {
                    "results": [
                        {
                            "campaign": {"resourceName": self.campaign["resourceName"]},
                            "adGroup": {"resourceName": self.group["resourceName"]},
                            "adGroupAd": deepcopy(self.ad_group_ad),
                        }
                    ]
                }
            )
        if "FROM ad_group " in query:
            return Reply(
                {
                    "results": [
                        {
                            "campaign": {"resourceName": self.campaign["resourceName"]},
                            "adGroup": deepcopy(self.group),
                        }
                    ]
                }
            )
        return super().__call__(req)


@pytest.mark.parametrize("name", NAMES)
def test_standalone_mutation_result_and_atomic_wire(name):
    from google_ads.runtime import dispatch

    provider = Mutator()
    response = dispatch(fixture(name), transport=provider)
    expected = yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())["success"][
        "response"
    ]
    if name == "update_bidding":
        expected["result"]["update_mask"] = ["target_spend.cpc_bid_ceiling_micros"]
    assert response == expected
    assert len(provider.writes) == 1
    req = provider.writes[0]
    assert req.write is True and req.body["partialFailure"] is False
    assert req.body["validateOnly"] is False
    assert len(req.body["mutateOperations"]) == 1
    if name == "update_campaign":
        op = req.body["mutateOperations"][0]["campaignOperation"]
        assert set(op["update"]) == {"resourceName", "name"}
        assert op["updateMask"] == "name"
    elif name == "update_bidding":
        op = req.body["mutateOperations"][0]["campaignOperation"]
        assert op["updateMask"] == "target_spend.cpc_bid_ceiling_micros"
        assert op["update"]["targetSpend"] == {"cpcBidCeilingMicros": "2000000"}
    elif name == "create_ad_group":
        assert req.body["mutateOperations"][0]["adGroupOperation"]["create"]["status"] == "PAUSED"
    elif name == "set_delivery_status":
        assert provider.campaign["status"] == "PAUSED"
        assert provider.group["status"] == "PAUSED"


@pytest.mark.parametrize("case", ["shared_flag", "two_users", "expected_amount"])
def test_budget_refuses_shared_or_observed_conflicting_state(case):
    from google_ads.runtime import dispatch

    provider = Mutator()
    p = fixture("update_campaign_budget")
    if case == "shared_flag":
        provider.budget["explicitlyShared"] = True
    elif case == "two_users":
        provider.two_budget_users = True
    else:
        p["action"]["input"]["expected_current_amount_micros"] = "10000000"
    response = dispatch(p, transport=provider)
    assert response["error_code"] == (
        "state_conflict" if case == "expected_amount" else "unsupported_configuration"
    )
    assert not provider.writes


@pytest.mark.parametrize("name", NAMES)
def test_unsupported_campaign_type_never_mutates(name):
    from google_ads.runtime import dispatch

    provider = Mutator()
    provider.campaign["advertisingChannelType"] = "DISPLAY"
    response = dispatch(fixture(name), transport=provider)
    assert response["error_code"] == "unsupported_configuration"
    assert not provider.writes


@pytest.mark.parametrize("name", NAMES)
def test_standalone_timeout_after_send_is_unknown_without_retry(name):
    from google_ads.runtime import dispatch

    provider = Mutator()
    provider.timeout = True
    response = dispatch(fixture(name), transport=provider)
    assert response["error_code"] == "outcome_unknown"
    assert response["definitely_no_external_effect"] is False
    assert len(provider.writes) == 1


def test_manual_cpc_strategy_switch_uses_leaf_mask_and_disables_enhancement():
    from google_ads.runtime import dispatch

    provider = Mutator()
    provider.campaign.pop("manualCpc")
    provider.campaign.update(biddingStrategyType="TARGET_SPEND", targetSpend={})
    p = fixture("update_bidding")
    p["action"]["input"].update(
        expected_current_strategy="MAXIMIZE_CLICKS", bidding={"strategy": "MANUAL_CPC"}
    )
    response = dispatch(p, transport=provider)
    assert response["ok"] is True, response
    operation = provider.writes[0].body["mutateOperations"][0]["campaignOperation"]
    assert operation["updateMask"] == "manual_cpc.enhanced_cpc_enabled"
    assert operation["update"]["manualCpc"] == {"enhancedCpcEnabled": False}


def test_budget_noop_uses_no_provider_mutate():
    from google_ads.runtime import dispatch

    provider = Mutator()
    p = fixture("update_campaign_budget")
    p["action"]["input"]["amount_micros"] = "20000000"
    response = dispatch(p, transport=provider)
    assert response["ok"] is True, response
    assert response["result"]["mutation_operation_count"] == 0
    assert not provider.writes


@pytest.mark.parametrize("name", ["update_campaign_budget", "update_bidding"])
def test_mutable_response_may_omit_output_only_metadata(name):
    from google_ads.runtime import dispatch

    class MutableOnly(Mutator):
        def __call__(self, req):
            reply = super().__call__(req)
            if req.write:
                for result in reply.body["mutateOperationResponses"]:
                    for value in result.values():
                        value.get("campaign", {}).pop("biddingStrategyType", None)
                        value.get("campaignBudget", {}).pop("period", None)
            return reply

    response = dispatch(fixture(name), transport=MutableOnly())
    assert response["ok"] is True, response


def test_unshared_budget_accepts_protojson_omitted_false_flag():
    from google_ads.runtime import dispatch

    provider = Mutator()
    provider.budget.pop("explicitlyShared")
    response = dispatch(fixture("update_campaign_budget"), transport=provider)
    assert response["ok"], response
    assert response["result"]["explicitly_shared"] is False
