"""Strict adapters for public listing endpoints, never authenticated actions."""
from __future__ import annotations

import json
import math
from urllib.parse import parse_qsl, urlsplit, urlencode

DEVPOST_LIST = "https://devpost.com/api/hackathons?status%5B%5D=open&per_page=20&page=1"


def devpost_listing_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query = dict(pairs)
        return bool(parsed.scheme == "https" and parsed.hostname == "devpost.com"
                    and parsed.port in {None, 443} and not parsed.username and not parsed.password
                    and parsed.path == "/api/hackathons" and not parsed.fragment
                    and len(pairs) == len(query) == 3 and set(query) == {"status[]", "per_page", "page"}
                    and query["status[]"] == "open" and query["per_page"] == "20"
                    and query["page"].isascii() and query["page"].isdigit() and 1 <= int(query["page"]) <= 1000)
    except (ValueError, TypeError):
        return False


def devpost_listing(body: str, url: str):
    """Listing data establishes discovery only; amounts and eligibility require rules."""
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("hackathons"), list):
        raise ValueError("Invalid Devpost listing")
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("Invalid Devpost pagination")
    count, per_page = meta.get("total_count"), meta.get("per_page")
    if (isinstance(count, bool) or not isinstance(count, int) or count < 0
            or per_page != 20 or isinstance(per_page, bool) or len(data["hackathons"]) > 20):
        raise ValueError("Invalid Devpost page bounds")
    links = []
    for row in data["hackathons"]:
        if (not isinstance(row, dict) or not isinstance(row.get("title"), str)
                or not isinstance(row.get("url"), str) or row.get("open_state") not in {"open", "upcoming", "closed"}):
            raise ValueError("Invalid Devpost entry")
        if row["open_state"] != "open":
            continue
        target = urlsplit(row["url"])
        if (target.hostname or "").endswith(".devpost.com") and target.path in {"", "/"}:
            links.append((row["url"], row["title"]))
    return links, {"listing_total": count, "listing_pages": max(1, math.ceil(count / 20))}


def devpost_next_page(body: str, url: str, hour: int) -> str | None:
    _, meta = devpost_listing(body, url)
    if int(dict(parse_qsl(urlsplit(url).query))["page"]) != 1 or meta["listing_pages"] <= 1:
        return None
    # Always read page one; rotate the remaining bounded public pages each hour.
    page = 2 + hour % min(999, meta["listing_pages"] - 1)
    return "https://devpost.com/api/hackathons?" + urlencode({"status[]": "open", "per_page": 20, "page": page})
