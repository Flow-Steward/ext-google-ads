"""Provider-specific semantic checks beyond the host's JSON Schema vocabulary."""

from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import unicodedata
from .errors import AdsError


def reject(message):
    raise AdsError("validation_failed", message)


def local_now(zone):
    return datetime.now(ZoneInfo(zone))


def timestamp(value, zone):
    try:
        raw = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        aware = raw.replace(tzinfo=ZoneInfo(zone))
        if aware.astimezone(timezone.utc).astimezone(aware.tzinfo).replace(tzinfo=None) != raw:
            raise ValueError
        if aware.utcoffset() != raw.replace(tzinfo=aware.tzinfo, fold=1).utcoffset():
            raise ValueError
        return aware
    except (ValueError, KeyError):
        reject("Use a real, unambiguous account-local calendar timestamp.")


def dates(values, zone, *, existing=None):
    current = existing or {}
    start = (
        timestamp(values.get("start_date_time", current.get("start_date_time")), zone)
        if values.get("start_date_time", current.get("start_date_time"))
        else None
    )
    end = (
        timestamp(values.get("end_date_time", current.get("end_date_time")), zone)
        if values.get("end_date_time", current.get("end_date_time"))
        else None
    )
    now = local_now(zone)
    if "start_date_time" in values and start is not None and start.date() < now.date():
        reject("The new start date must not be in the account's past.")
    if "end_date_time" in values and end is not None and end.date() < now.date():
        reject("The new end date must not be in the account's past.")
    if end is not None and start is not None and end < start:
        reject("The campaign end must not precede its start.")


def schedule(value):
    if value["mode"] == "all_time":
        return []
    by_day = {}
    for interval in value["intervals"]:
        start = interval["start_hour"] * 60 + interval["start_minute"]
        end = interval["end_hour"] * 60 + interval["end_minute"]
        if end > 1440 or end <= start:
            reject(
                "Split overnight intervals across days; end must follow start within the same day."
            )
        by_day.setdefault(interval["day"], []).append((start, end))
    for intervals in by_day.values():
        if len(intervals) > 6:
            reject("At most six schedule intervals are allowed per day.")
        ordered = sorted(intervals)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            reject("Schedule intervals on the same day must not overlap.")
    return deepcopy(value["intervals"])


def rsa(content):
    for field, limit in (("headlines", 30), ("descriptions", 90)):
        if field not in content:
            continue
        seen = set()
        for asset in content[field]:
            text = asset["text"]
            length = sum(2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1 for c in text)
            if not text.strip() or text in seen or length > limit:
                reject(
                    "RSA text must be nonempty, unique within its list and within Google character limits."
                )
            seen.add(text)
    if content.get("path2") and not content.get("path1"):
        reject("A nonempty second display path requires the first path.")
    for value in content.get("final_urls", []):
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or any(c.isspace() or ord(c) < 32 for c in value)
            ):
                raise ValueError
        except ValueError:
            reject("Landing URLs must be valid HTTP(S) URLs without embedded credentials.")


def keyword_text(value):
    value = value.strip()
    if not value or len(value) > 80 or len(value.split()) > 10:
        reject(
            "Keyword text must contain at most80 characters and ten words after trimming outer spaces."
        )
    return value


def currency(actual, expected):
    if actual != expected:
        reject("The requested currency does not match the current advertising account.")


def specification(value, account):
    value = deepcopy(value)
    currency(account["currency_code"], value["currency_code"])
    dates(value, account["time_zone"])
    schedule(value["targeting"]["schedule"])
    geo = value["targeting"]["geo_target_constants"]
    if len(set(geo)) != len(geo):
        reject("Geo targets must be unique.")
    seen = {"budget", "campaign"}

    def key(value):
        if value in seen or value.startswith("geo_"):
            reject("Local keys must be unique and not use reserved mapping keys.")
        seen.add(value)

    manual = value["bidding"]["strategy"] == "MANUAL_CPC"
    for group in value["ad_groups"]:
        key(group["key"])
        if not group["name"].strip():
            reject("Ad group names must not be blank.")
        if not manual and "cpc_bid_micros" in group:
            reject("CPC inputs require Manual CPC.")
        for ad in group["ads"]:
            key(ad["key"])
            rsa(ad["content"])
        identities = set()
        for item in group["keywords"]:
            key(item["key"])
            item["text"] = keyword_text(item["text"])
            identity = (item["text"], item["match_type"])
            if identity in identities:
                reject("Duplicate keyword identity in the same ad group.")
            identities.add(identity)
            if not manual and "cpc_bid_micros" in item:
                reject("CPC inputs require Manual CPC.")
            if manual and "cpc_bid_micros" not in item and "cpc_bid_micros" not in group:
                reject("Manual CPC requires a group or explicit keyword CPC.")
    if not value["name"].strip():
        reject("Campaign name must not be blank.")
    return value


def bidding_wire(value):
    strategy = value["strategy"]
    if strategy == "MANUAL_CPC":
        return {"manualCpc": {}}
    if strategy == "MAXIMIZE_CLICKS":
        return {
            "targetSpend": (
                {"cpcBidCeilingMicros": value["cpc_bid_ceiling_micros"]}
                if "cpc_bid_ceiling_micros" in value
                else {}
            )
        }
    return {
        "maximizeConversions": (
            {"targetCpaMicros": value["target_cpa_micros"]} if "target_cpa_micros" in value else {}
        )
    }


def rsa_wire(value):
    ad = {}
    if "final_urls" in value:
        ad["finalUrls"] = value["final_urls"]
    rsa_value = {}
    for source, target in (("headlines", "headlines"), ("descriptions", "descriptions")):
        if source in value:
            rsa_value[target] = [
                {
                    "text": item["text"],
                    **({"pinnedField": item["pinned_field"]} if "pinned_field" in item else {}),
                }
                for item in value[source]
            ]
    for field in ("path1", "path2"):
        if field in value:
            rsa_value[field] = value[field]
    if rsa_value:
        ad["responsiveSearchAd"] = rsa_value
    return ad


def schedule_wire(interval):
    minute = {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}
    return {
        "dayOfWeek": interval["day"],
        "startHour": interval["start_hour"],
        "startMinute": minute[interval["start_minute"]],
        "endHour": interval["end_hour"],
        "endMinute": minute[interval["end_minute"]],
    }
