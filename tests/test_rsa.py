"""RSA content edits use AdService and retain explicit list/status semantics."""

from copy import deepcopy
from pathlib import Path
import yaml
import pytest
from test_boundary import fixture
from test_mutations import Mutator, merge

ROOT = Path(__file__).resolve().parents[1]


class Ads(Mutator):
    def __init__(self):
        super().__init__()
        content = fixture("create_responsive_search_ad")["action"]["input"]["responsive_search_ad"]
        from google_ads.validation import rsa_wire

        self.ad_group_ad["ad"].update(rsa_wire(content))
        self.ad_group_ad["policySummary"].update(
            reviewStatus="REVIEW_IN_PROGRESS", approvalStatus="UNKNOWN"
        )
        self.shared = False
        self.missing = False

    def __call__(self, req):
        from google_ads.transport import Reply

        if req.url.endswith("ads:mutate"):
            self.writes.append(req)
            if self.timeout:
                raise TimeoutError("private provider detail")
            merge(self.ad_group_ad["ad"], req.body["operations"][0]["update"])
            return Reply(
                {
                    "results": [
                        {
                            "resourceName": self.ad_group_ad["ad"]["resourceName"],
                            "ad": deepcopy(self.ad_group_ad["ad"]),
                        }
                    ]
                },
                "synthetic-google-request-001",
            )
        query = (req.body or {}).get("query", "")
        if "FROM ad_group_ad " in query and self.missing:
            return Reply({"results": []})
        result = super().__call__(req)
        if "FROM ad_group_ad " in query and self.shared:
            extra = deepcopy(result.body["results"][0])
            extra["adGroupAd"]["resourceName"] = "customers/1234567890/adGroupAds/2002~3001"
            result.body["results"].append(extra)
        return result


@pytest.mark.parametrize("name", ["create_responsive_search_ad", "update_responsive_search_ad"])
def test_rsa_public_results_and_service_wire(name):
    from google_ads.runtime import dispatch

    provider = Ads()
    p = fixture(name)
    response = dispatch(p, transport=provider)
    expected = yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())["success"][
        "response"
    ]
    assert response == expected
    assert len(provider.writes) == 1
    req = provider.writes[0]
    if name.startswith("update"):
        assert req.url.endswith("/ads:mutate")
        operation = req.body["operations"][0]
        assert operation["updateMask"] == "final_urls"
        assert set(operation["update"]) == {"resourceName", "finalUrls"}
    else:
        assert req.body["mutateOperations"][0]["adGroupAdOperation"]["create"]["status"] == "PAUSED"
    assert provider.ad_group_ad["status"] == "PAUSED"


@pytest.mark.parametrize(
    "patch",
    [
        {"path1": "", "path2": "required"},
        {"final_urls": ["https://user:secret@example.com/"]},
        {"headlines": [{"text": "same"}] * 3},
    ],
)
def test_invalid_rsa_full_merged_content_never_writes(patch):
    from google_ads.runtime import dispatch

    provider = Ads()
    p = fixture("update_responsive_search_ad")
    p["action"]["input"]["patch"] = patch
    response = dispatch(p, transport=provider)
    assert response["error_code"] == "validation_failed"
    assert not provider.writes


def test_rsa_replaces_asset_lists_and_retains_omitted_fields():
    from google_ads.runtime import dispatch

    provider = Ads()
    before = deepcopy(provider.ad_group_ad["ad"])
    p = fixture("update_responsive_search_ad")
    p["action"]["input"]["patch"] = {
        "headlines": [
            {"text": "New One", "pinned_field": "HEADLINE_1"},
            {"text": "New Two"},
            {"text": "New Three"},
        ],
        "path1": "",
    }
    response = dispatch(p, transport=provider)
    assert response["ok"], response
    ad = provider.ad_group_ad["ad"]
    assert len(ad["responsiveSearchAd"]["headlines"]) == 3
    assert ad["responsiveSearchAd"]["headlines"][0]["pinnedField"] == "HEADLINE_1"
    assert ad["responsiveSearchAd"]["descriptions"] == before["responsiveSearchAd"]["descriptions"]
    assert ad["finalUrls"] == before["finalUrls"]
    assert (
        provider.writes[0].body["operations"][0]["updateMask"]
        == "responsive_search_ad.headlines,responsive_search_ad.path1"
    )


@pytest.mark.parametrize(
    "flag,code", [("shared", "unsupported_configuration"), ("missing", "resource_not_found")]
)
def test_rsa_update_refuses_ambiguous_or_missing_association(flag, code):
    from google_ads.runtime import dispatch

    provider = Ads()
    setattr(provider, flag, True)
    response = dispatch(fixture("update_responsive_search_ad"), transport=provider)
    assert response["error_code"] == code
    assert not provider.writes


@pytest.mark.parametrize("name", ["create_responsive_search_ad", "update_responsive_search_ad"])
def test_rsa_timeout_never_retries(name):
    from google_ads.runtime import dispatch

    provider = Ads()
    provider.timeout = True
    response = dispatch(fixture(name), transport=provider)
    assert response["error_code"] == "outcome_unknown"
    assert response["definitely_no_external_effect"] is False
    assert len(provider.writes) == 1
