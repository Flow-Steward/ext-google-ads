"""Ordinary read actions, hierarchy constraints and lossless provider paging."""

from copy import deepcopy
from pathlib import Path
import yaml
import pytest
from test_boundary import fixture

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = "customers/1234567890/campaigns/1001"
GROUP = "customers/1234567890/adGroups/2001"
CUSTOMER = {
    "id": "1234567890",
    "resourceName": "customers/1234567890",
    "descriptiveName": "Synthetic client account",
    "manager": False,
    "testAccount": True,
    "status": "ENABLED",
    "currencyCode": "EUR",
    "timeZone": "Europe/Vilnius",
    "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
}
CAMPAIGN_ROW = {
    "campaign": {
        "id": "1001",
        "resourceName": CAMPAIGN,
        "name": "Synthetic Search",
        "status": "PAUSED",
        "advertisingChannelType": "SEARCH",
        "campaignBudget": "customers/1234567890/campaignBudgets/5001",
        "startDateTime": "2026-11-01 00:00:00",
        "networkSettings": {
            "targetGoogleSearch": True,
            "targetSearchNetwork": False,
            "targetContentNetwork": False,
            "targetPartnerSearchNetwork": False,
        },
        "manualCpc": {},
        "biddingStrategyType": "MANUAL_CPC",
        "servingStatus": "NONE",
        "primaryStatus": "PAUSED",
        "primaryStatusReasons": ["CAMPAIGN_PAUSED"],
        "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        "geoTargetTypeSetting": {
            "positiveGeoTargetType": "PRESENCE",
            "negativeGeoTargetType": "PRESENCE",
        },
    },
    "campaignBudget": {
        "resourceName": "customers/1234567890/campaignBudgets/5001",
        "amountMicros": "10000000",
        "explicitlyShared": False,
    },
}
GROUP_ROW = {
    "campaign": {"resourceName": CAMPAIGN},
    "adGroup": {
        "resourceName": GROUP,
        "campaign": CAMPAIGN,
        "name": "Synthetic group",
        "status": "PAUSED",
        "type": "SEARCH_STANDARD",
        "cpcBidMicros": "500000",
    },
}
AD_ROW = {
    "campaign": {"resourceName": CAMPAIGN},
    "adGroup": {"resourceName": GROUP},
    "adGroupAd": {
        "resourceName": "customers/1234567890/adGroupAds/2001~3001",
        "adGroup": GROUP,
        "status": "PAUSED",
        "ad": {
            "resourceName": "customers/1234567890/ads/3001",
            "type": "RESPONSIVE_SEARCH_AD",
            "finalUrls": ["https://example.invalid/"],
            "responsiveSearchAd": {
                "headlines": [
                    {"text": "Synthetic headline one"},
                    {"text": "Synthetic headline two"},
                    {"text": "Synthetic headline three"},
                ],
                "descriptions": [
                    {"text": "Synthetic description one"},
                    {"text": "Synthetic description two"},
                ],
                "path1": "",
                "path2": "",
            },
        },
        "policySummary": {
            "approvalStatus": "APPROVED",
            "reviewStatus": "REVIEWED",
            "policyTopicEntries": [],
        },
    },
}
KEYWORD_ROW = {
    "campaign": {"resourceName": CAMPAIGN},
    "adGroupCriterion": {
        "resourceName": "customers/1234567890/adGroupCriteria/2001~4001",
        "adGroup": GROUP,
        "status": "PAUSED",
        "negative": False,
        "keyword": {"text": "synthetic keyword", "matchType": "EXACT"},
        "cpcBidMicros": "500000",
    },
}
GEO_ROW = {
    "campaignCriterion": {
        "resourceName": "customers/1234567890/campaignCriteria/1001~6001",
        "status": "ENABLED",
        "negative": False,
        "location": {"geoTargetConstant": "geoTargetConstants/2440"},
        "type": "LOCATION",
    }
}


class Provider:
    def __init__(self):
        self.seen = []
        self.campaign_pages = {"": {"results": [deepcopy(CAMPAIGN_ROW)]}}

    def __call__(self, request):
        from google_ads.transport import Reply

        self.seen.append(request)
        if request.url.endswith("customers:listAccessibleCustomers"):
            return Reply({"resourceNames": ["customers/1234567890"]})
        query = (request.body or {}).get("query", "")
        if "FROM customer_client" in query:
            return Reply(
                {
                    "results": [
                        {
                            "customerClient": {
                                "id": "1234567890",
                                "clientCustomer": "customers/1234567890",
                                "descriptiveName": "Synthetic client account",
                                "manager": False,
                                "testAccount": True,
                                "level": "1",
                            }
                        }
                    ]
                }
            )
        if "FROM customer " in query:
            return Reply([{"results": [{"customer": deepcopy(CUSTOMER)}]}])
        if "FROM campaign " in query:
            if "WHERE campaign.resource_name =" in query:
                return Reply({"results": [deepcopy(CAMPAIGN_ROW)]})
            return Reply(
                deepcopy(
                    self.campaign_pages.get(request.body.get("pageToken", ""), {"results": []})
                )
            )
        if "FROM ad_group_ad " in query:
            return Reply({"results": [deepcopy(AD_ROW)]})
        if "FROM ad_group_criterion " in query:
            return Reply({"results": [deepcopy(KEYWORD_ROW)]})
        if "FROM ad_group " in query:
            return Reply({"results": [deepcopy(GROUP_ROW)]})
        if "FROM campaign_criterion " in query:
            return Reply({"results": [] if "'KEYWORD'" in query else [deepcopy(GEO_ROW)]})
        pytest.fail(f"Unrecognized provider query: {query}")


@pytest.mark.parametrize(
    "name",
    [
        "list_accessible_accounts",
        "list_manager_clients",
        "list_campaigns",
        "get_campaign",
        "list_ad_groups",
        "list_ads",
        "list_keywords",
        "list_targeting",
    ],
)
def test_read_operation_matches_full_contract_fixture(name):
    from google_ads.runtime import dispatch

    provider = Provider()
    result = dispatch(fixture(name), transport=provider)
    expected = yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())["success"][
        "response"
    ]
    assert result == expected
    assert all("pageSize" not in (req.body or {}) for req in provider.seen)
    assert all("mutate" not in req.url for req in provider.seen)


def test_partial_provider_page_is_refetched_verified_and_not_lost():
    from google_ads.runtime import dispatch

    provider = Provider()
    a, b, c = [deepcopy(CAMPAIGN_ROW) for _ in range(3)]
    b["campaign"]["resourceName"] = "customers/1234567890/campaigns/1002"
    c["campaign"]["resourceName"] = "customers/1234567890/campaigns/1003"
    provider.campaign_pages = {
        "": {"results": [a, b], "nextPageToken": "second_page"},
        "second_page": {"results": [c]},
    }
    p = fixture("list_campaigns")
    p["action"]["input"]["page_size"] = 1
    resources = []
    for _ in range(3):
        result = dispatch(p, transport=provider)
        assert result["ok"] is True, result
        resources.extend(row["resource_name"] for row in result["result"]["items"])
        cursor = result["result"]["next_cursor"]
        if not cursor:
            break
        p["action"]["input"]["cursor"] = cursor
    assert resources == [
        CAMPAIGN,
        "customers/1234567890/campaigns/1002",
        "customers/1234567890/campaigns/1003",
    ]
    assert cursor is None


def test_changed_refetched_page_requires_explicit_restart():
    from google_ads.runtime import dispatch

    provider = Provider()
    provider.campaign_pages[""]["results"] = [deepcopy(CAMPAIGN_ROW), deepcopy(CAMPAIGN_ROW)]
    p = fixture("list_campaigns")
    p["action"]["input"]["page_size"] = 1
    first = dispatch(p, transport=provider)
    assert first["ok"] is True, first
    p["action"]["input"]["cursor"] = first["result"]["next_cursor"]
    provider.campaign_pages[""]["results"][1]["campaign"]["name"] = "Changed externally"
    result = dispatch(p, transport=provider)
    assert result["error_code"] == "state_conflict"
    assert result["restart_required"] is True


def test_cursor_cannot_be_reused_with_other_filters_or_connection():
    from google_ads.runtime import dispatch

    provider = Provider()
    provider.campaign_pages[""]["results"] *= 2
    p = fixture("list_campaigns")
    p["action"]["input"]["page_size"] = 1
    first = dispatch(p, transport=provider)
    assert first["ok"] is True, first
    p["action"]["input"]["cursor"] = first["result"]["next_cursor"]
    p["action"]["target"]["connection"]["connection_id"] = "conn_other"
    result = dispatch(p, transport=provider)
    assert result["error_code"] == "state_conflict"


def test_resource_prefix_mismatch_fails_before_resource_query():
    from google_ads.runtime import dispatch

    p = fixture("list_ad_groups")
    p["action"]["input"]["campaign"] = "customers/1111111111/campaigns/1001"
    provider = Provider()
    result = dispatch(p, transport=provider)
    assert result["error_code"] == "resource_account_mismatch"
    assert not any("FROM ad_group " in (req.body or {}).get("query", "") for req in provider.seen)


def test_empty_success_is_distinct_from_provider_failure():
    from google_ads.runtime import dispatch
    from google_ads.errors import AdsError

    provider = Provider()
    provider.campaign_pages[""] = {"results": []}
    empty = dispatch(fixture("list_campaigns"), transport=provider)
    assert empty["ok"] is True and empty["result"]["items"] == []

    def refused(req):
        raise AdsError("permission_denied", "Access was lost.")

    failed = dispatch(fixture("list_campaigns"), transport=refused)
    assert failed["ok"] is False and failed["error_code"] == "permission_denied"


def test_nested_manager_routes_preserve_concrete_access_paths():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    class Nested(Provider):
        def __call__(self, req):
            query = (req.body or {}).get("query", "")
            if "FROM customer_client" not in query:
                return super().__call__(req)
            assert req.headers["login-customer-id"] == "9876543210"
            if "/customers/9876543210/" in req.url:
                rows = [
                    {
                        "customerClient": {
                            "id": "2222222222",
                            "manager": True,
                            "descriptiveName": "Nested manager",
                            "testAccount": True,
                        }
                    }
                ]
            else:
                rows = [
                    {
                        "customerClient": {
                            "id": "3333333333",
                            "manager": False,
                            "descriptiveName": "Nested client",
                            "testAccount": True,
                        }
                    }
                ]
            return Reply({"results": rows})

    result = dispatch(fixture("list_manager_clients"), transport=Nested())
    assert result["ok"] is True, result
    assert [x["access_path"] for x in result["result"]["items"]] == [
        ["9876543210", "2222222222"],
        ["9876543210", "2222222222", "3333333333"],
    ]
    assert result["result"]["truncated"] is False


def test_inaccessible_manager_branch_is_diagnostic_not_silently_empty():
    from google_ads.runtime import dispatch
    from google_ads.errors import AdsError
    from google_ads.transport import Reply

    def send(req):
        if "/customers/9876543210/" in req.url:
            return Reply({"results": [{"customerClient": {"id": "2222222222", "manager": True}}]})
        raise AdsError("permission_denied", "The nested manager is inaccessible.")

    result = dispatch(fixture("list_manager_clients"), transport=send)
    assert result["ok"] is True, result
    item = result["result"]["items"][0]
    assert item["branch_status"] == "inaccessible"
    assert item["branch_error"]["code"] == "permission_denied"
    assert result["result"]["truncated"] is True


def test_manager_cycle_is_bounded_and_marked():
    from google_ads.runtime import dispatch
    from google_ads.transport import Reply

    seen = []

    def send(req):
        seen.append(req)
        return Reply({"results": [{"customerClient": {"id": "9876543210", "manager": True}}]})

    result = dispatch(fixture("list_manager_clients"), transport=send)
    assert result["ok"] is True, result
    assert len(seen) == 1
    assert result["result"]["items"][0]["branch_status"] == "cycle_detected"
    assert result["result"]["truncated"] is True


def test_expired_or_tampered_cursor_requires_restart(monkeypatch):
    import google_ads.paging as paging
    from google_ads.runtime import dispatch

    now = [1000]
    monkeypatch.setattr(paging.time, "time", lambda: now[0])
    provider = Provider()
    provider.campaign_pages[""]["results"] *= 2
    p = fixture("list_campaigns")
    p["action"]["input"]["page_size"] = 1
    first = dispatch(p, transport=provider)
    cursor = first["result"]["next_cursor"]
    p["action"]["input"]["cursor"] = cursor
    now[0] = 5000
    expired = dispatch(p, transport=provider)
    assert expired["error_code"] == "state_conflict" and expired["restart_required"] is True
    now[0] = 1000
    p["action"]["input"]["cursor"] = "x" + cursor[1:]
    tampered = dispatch(p, transport=provider)
    assert tampered["error_code"] == "state_conflict"


def test_portfolio_strategy_is_readable_but_not_advertised_writable():
    from google_ads.runtime import dispatch

    provider = Provider()
    provider.campaign_pages[""]["results"][0]["campaign"]["biddingStrategy"] = (
        "customers/1234567890/biddingStrategies/8"
    )
    result = dispatch(fixture("list_campaigns"), transport=provider)
    assert result["ok"] is True, result
    assert result["result"]["items"][0]["supported_for_writes"] is False


def test_out_of_int64_provider_money_is_not_returned_as_valid(monkeypatch):
    from google_ads.runtime import dispatch

    monkeypatch.setitem(GROUP_ROW["adGroup"], "cpcBidMicros", "9223372036854775808")
    result = dispatch(fixture("list_ad_groups"), transport=Provider())
    assert result["ok"] is False
    assert result["error_code"] == "provider_unavailable"
