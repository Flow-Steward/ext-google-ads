"""Pure projections from pinned Google REST JSON to public read contracts."""


def campaign_summary(row):
    c = row["campaign"]
    return {
        "resource_name": c["resourceName"],
        "name": c.get("name", ""),
        "status": c.get("status", "UNSPECIFIED"),
        "advertising_channel_type": c.get("advertisingChannelType", "UNSPECIFIED"),
        "campaign_budget": c.get("campaignBudget"),
        "supported_for_writes": c.get("advertisingChannelType") == "SEARCH"
        and not c.get("biddingStrategy")
        and c.get("biddingStrategyType")
        in {"MANUAL_CPC", "TARGET_SPEND", "MAXIMIZE_CLICKS", "MAXIMIZE_CONVERSIONS"},
    }


def networks(c):
    n = c.get("networkSettings")
    if not isinstance(n, dict):
        return None
    return {
        "target_google_search": n.get("targetGoogleSearch", False),
        "target_search_network": n.get("targetSearchNetwork", False),
        "target_content_network": n.get("targetContentNetwork", False),
        "target_partner_search_network": n.get("targetPartnerSearchNetwork", False),
    }


def campaign_detail(row):
    c = row["campaign"]
    budget = row.get("campaignBudget", {})
    strategy = c.get("biddingStrategyType", "UNSPECIFIED")
    if strategy == "TARGET_SPEND":
        strategy = "MAXIMIZE_CLICKS"
    return {
        **campaign_summary(row),
        "start_date_time": c.get("startDateTime"),
        "end_date_time": c.get("endDateTime"),
        "network_settings": networks(c),
        "budget": {
            "resource_name": budget.get("resourceName", c.get("campaignBudget")),
            "amount_micros": budget.get("amountMicros"),
            "explicitly_shared": budget.get("explicitlyShared", False),
        },
        "bidding": {
            "strategy_type": strategy,
            "strategy_resource": c.get("biddingStrategy") or None,
            "cpc_bid_ceiling_micros": c.get("targetSpend", {}).get("cpcBidCeilingMicros"),
            "target_cpa_micros": c.get("maximizeConversions", {}).get("targetCpaMicros"),
        },
        "serving_status": c.get("servingStatus"),
        "primary_status": c.get("primaryStatus"),
        "primary_status_reasons": c.get("primaryStatusReasons", []),
        "contains_eu_political_advertising": c.get("containsEuPoliticalAdvertising"),
    }


def group_summary(row):
    a = row["adGroup"]
    return {
        "resource_name": a["resourceName"],
        "campaign": a.get("campaign", row.get("campaign", {}).get("resourceName")),
        "name": a.get("name", ""),
        "status": a.get("status", "UNSPECIFIED"),
        "type": a.get("type", "UNSPECIFIED"),
        "cpc_bid_micros": a.get("cpcBidMicros"),
    }


def ad_summary(row):
    ga = row["adGroupAd"]
    ad = ga["ad"]
    rsa = ad.get("responsiveSearchAd")
    content = None
    if isinstance(rsa, dict):
        content = {
            "headlines": [
                {"text": a["text"], "pinned_field": a.get("pinnedField")}
                for a in rsa.get("headlines", [])
            ],
            "descriptions": [
                {"text": a["text"], "pinned_field": a.get("pinnedField")}
                for a in rsa.get("descriptions", [])
            ],
            "path1": rsa.get("path1", ""),
            "path2": rsa.get("path2", ""),
        }
    policy = ga.get("policySummary", {})
    return {
        "ad_group_ad": ga["resourceName"],
        "ad": ad["resourceName"],
        "ad_group": ga.get("adGroup", row.get("adGroup", {}).get("resourceName")),
        "campaign": row["campaign"]["resourceName"],
        "type": ad.get("type", "UNSPECIFIED"),
        "status": ga.get("status", "UNSPECIFIED"),
        "responsive_search_ad": content,
        "final_urls": ad.get("finalUrls", []),
        "policy": {
            "approval_status": policy.get("approvalStatus"),
            "review_status": policy.get("reviewStatus"),
            "topic_entries": [p.get("topic", "") for p in policy.get("policyTopicEntries", [])],
        },
    }


def keyword_summary(row):
    if "adGroupCriterion" in row:
        c = row["adGroupCriterion"]
        extra = {
            "scope": "ad_group",
            "ad_group": c["adGroup"],
            "cpc_bid_micros": c.get("cpcBidMicros"),
        }
    else:
        c = row["campaignCriterion"]
        extra = {"scope": "campaign"}
    return {
        **extra,
        "resource_name": c["resourceName"],
        "campaign": row["campaign"]["resourceName"],
        "text": c["keyword"]["text"],
        "match_type": c["keyword"]["matchType"],
        "status": c.get("status", "UNSPECIFIED"),
        "negative": c.get("negative", False),
    }


def targeting_summary(row):
    c = row["campaignCriterion"]
    result = {"resource_name": c["resourceName"]}
    if "location" in c:
        return {
            **result,
            "kind": "geo",
            "geo_target_constant": c["location"]["geoTargetConstant"],
            "negative": c.get("negative", False),
            "status": c.get("status", "UNSPECIFIED"),
        }
    if "language" in c:
        return {
            **result,
            "kind": "legacy_language",
            "language_constant": c["language"]["languageConstant"],
            "serving": False,
            "legacy": True,
        }
    a = c["adSchedule"]
    minutes = {"ZERO": 0, "FIFTEEN": 15, "THIRTY": 30, "FORTY_FIVE": 45}
    return {
        **result,
        "kind": "ad_schedule",
        "day": a["dayOfWeek"],
        "start_hour": a.get("startHour", 0),
        "end_hour": a.get("endHour", 0),
        "start_minute": minutes.get(a.get("startMinute", "ZERO")),
        "end_minute": minutes.get(a.get("endMinute", "ZERO")),
    }
