"""IPOAlerts API adapter: header authentication, complete pagination, bounded IO."""

import asyncio
import json
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import ValidationError

from packages.providers.ipo import IPOBatch
from packages.providers.market import FeedError, Issue, Premium

URL = "https://api.ipoalerts.in/ipos"
STATUSES = ("open", "upcoming", "announced")
EMPTY = (None, "", "-", "–", "—")


def optional_day(value):
    return None if value in EMPTY else date.fromisoformat(value).isoformat()


def normalize(row, observed_at):
    status = row["status"]
    if status not in (*STATUSES, "closed", "listed"):
        raise ValueError("Unknown status")
    if row.get("typeOfIssue", "IPO") not in (None, "IPO") or row.get("type") == "DEBT":
        return None
    board = {"EQ": "Mainboard", "SME": "SME", None: "Unknown"}.get(row.get("type"))
    if board is None or (board == "Unknown" and status != "announced"):
        raise ValueError("Unknown security type")
    source = row.get("source")
    if source not in ("nse", "bse"):
        raise ValueError("Unknown exchange")
    identity = {"provider_namespace": "IPOALERTS", "provider_id": str(row["id"])}
    symbol = row.get("symbol")
    if symbol:
        if not re.fullmatch(r"[A-Z0-9&._-]{1,40}", symbol):
            raise ValueError("Invalid symbol")
        identity["nse_symbol" if source == "nse" else "bse_symbol"] = symbol
    nse_url = row.get("nseInfoUrl")
    if nse_url and urlsplit(nse_url).hostname in ("nseindia.com", "www.nseindia.com"):
        linked_symbol = parse_qs(urlsplit(nse_url).query).get("symbol", [None])[0]
        if linked_symbol:
            if linked_symbol != symbol:
                raise ValueError("Exchange link conflicts with symbol")
            identity["nse_symbol"] = linked_symbol
    # A BSE issue number is not a stock/scrip code.
    bse_url = row.get("bseInfoUrl")
    if bse_url and urlsplit(bse_url).hostname in ("bseindia.com", "www.bseindia.com"):
        issue_id = parse_qs(urlsplit(bse_url).query).get("IPONo", [None])[0]
        if issue_id:
            identity["bse_issue_id"] = issue_id
    low = high = None
    if row.get("priceRange") not in EMPTY:
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*", row["priceRange"]
        )
        if not match:
            raise ValueError("Invalid price band")
        low, high = match[1], match[2] or match[1]
    size = None
    if row.get("issueSize") not in EMPTY:
        match = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*cr\s*", row["issueSize"], re.I)
        if not match:
            raise ValueError("Issue size must use crore units")
        size = Decimal(match[1].replace(",", ""))
    schedule = row.get("schedule") or []
    events = {item["event"].casefold(): optional_day(item["date"]) for item in schedule}
    values = {
        **identity,
        "source_url": URL,
        "source_timestamp": observed_at,
        "official_status": status.upper(),
        "issue": {
            "slug": row["slug"],
            "name": row["name"],
            "sector": "Unclassified",
            "board": board,
            "exchange": source.upper(),
            "status": "UPCOMING" if status == "announced" else status.upper(),
            "open_date": optional_day(row.get("startDate")),
            "close_date": optional_day(row.get("endDate")),
            "listing_date": optional_day(row.get("listingDate")),
            "price_low": low,
            "price_high": high,
            "lot_size": row.get("minQty"),
            "issue_size": size,
            "source_url": URL,
            "exchange_url": row.get("nseInfoUrl") or bse_url,
            "rhp_url": row.get("prospectusUrl"),
            "verification_status": "UNVERIFIED",
        },
        "allotment_date": events.get("allotment finalization"),
        "refund_date": events.get("refund initiation"),
        "demat_credit_date": events.get("share credit"),
        "provider_details": {
            "about": row.get("about"),
            "strengths": row.get("strengths") or [],
            "risks": row.get("risks") or [],
            "schedule": schedule,
            "minimum_amount": row.get("minAmount"),
            "logo_url": row.get("logo"),
            "info_url": row.get("infoUrl"),
        },
    }
    return Issue.model_validate(values).model_dump(mode="json")


def normalize_gmp(row):
    """A missing quote is not zero; retain the provider's observation timestamp."""
    gmp = row.get("gmp")
    if not isinstance(gmp, dict):
        return None
    aggregations = gmp.get("aggregations") or {}
    value = aggregations.get("mean")
    # Some provider responses can contain verified constituent quotes before the
    # aggregate is materialized. Preserve those observations when all fields
    # needed for a traceable quote are present.
    if value is None:
        sources = gmp.get("sources") or []
        if not isinstance(sources, list) or len(sources) > 50:
            raise ValueError("Invalid GMP sources")
        values = [
            Decimal(str(source["gmpPrice"]))
            for source in sources
            if isinstance(source, dict) and source.get("gmpPrice") is not None
        ]
        if values:
            value = sum(values, Decimal()) / len(values)
    if value is None:
        return None
    if not gmp.get("lastUpdatedAt"):
        raise ValueError("GMP timestamp required")
    return Premium(
        provider_namespace="IPOALERTS",
        provider_id=str(row["id"]),
        value=value,
        source_timestamp=gmp["lastUpdatedAt"],
        source_url=URL + "/" + str(row["id"]),
    ).model_dump(mode="json")


class IPOAlerts:
    name = "IPOALERTS"
    authority = "LICENSED"

    def __init__(self, key, *, page_size=3, transport=None, sleep=asyncio.sleep):
        self.key, self.transport, self.sleep = key, transport, sleep
        self.page_size = page_size

    async def request(self, client, params, deadline):
        for attempt in range(3):
            if time.monotonic() >= deadline:
                raise FeedError("IPOALERTS_TIME_BUDGET")
            try:
                async with client.stream("GET", URL, params=params) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise FeedError("IPOALERTS_AUTH_FAILED")
                    if status == 429:
                        raise FeedError("IPOALERTS_RATE_LIMITED")
                    if status >= 500:
                        raise httpx.TransportError("Upstream unavailable")
                    if status != 200:
                        raise FeedError("IPOALERTS_HTTP_ERROR")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 5_000_000:
                            raise FeedError("IPOALERTS_PAYLOAD_TOO_LARGE")
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode("utf-8")
                try:
                    body = json.loads(raw)
                    meta, rows = body["meta"], body["ipos"]
                    if not isinstance(rows, list) or not isinstance(meta, dict):
                        raise ValueError()
                    if meta.get("info"):
                        raise FeedError("IPOALERTS_INCOMPLETE_ACCESS")
                    for key in ("count", "countOnPage", "totalPages", "page", "limit"):
                        if type(meta.get(key)) is not int or meta[key] < 0:
                            raise ValueError()
                    if (
                        meta["page"] != params["page"]
                        or meta["countOnPage"] != len(rows)
                        or len(rows) > 100
                        or meta["limit"] < 1
                        or (not rows and meta["count"] != 0)
                        or meta["totalPages"] > 20
                    ):
                        raise ValueError()
                    return raw, meta, rows
                except (ValueError, KeyError, TypeError):
                    raise FeedError("IPOALERTS_SCHEMA_CHANGED") from None
            except httpx.TransportError:
                if attempt == 2:
                    raise FeedError("IPOALERTS_UNAVAILABLE") from None
                await self.sleep(2**attempt)

    async def batches(self, deadline):
        if not self.key:
            raise FeedError("IPOALERTS_KEY_REQUIRED")
        async with httpx.AsyncClient(
            headers={"x-api-key": self.key, "Accept": "application/json"},
            timeout=20,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            first_request = True
            for status in STATUSES:
                # Buffer one complete status; a failed page cannot publish a partial catalogue.
                pages, seen, total = [], set(), None
                for page in range(1, 21):
                    if not first_request:
                        await self.sleep(10.1)  # Default free tier: six list requests/minute.
                    first_request = False
                    raw, meta, rows = await self.request(
                        client,
                        {
                            "status": status,
                            "page": page,
                            "limit": self.page_size,
                            "includeGmp": "true",
                        },
                        deadline,
                    )
                    if total is not None and total != (meta["count"], meta["totalPages"]):
                        raise FeedError("IPOALERTS_PAGINATION_CHANGED")
                    total = (meta["count"], meta["totalPages"])
                    records, errors = [], []
                    for row in rows:
                        key = str(row.get("id", "")) if isinstance(row, dict) else ""
                        if not key or key in seen:
                            raise FeedError("IPOALERTS_PAGINATION_CHANGED")
                        seen.add(key)
                        try:
                            if row.get("status") != status:
                                raise ValueError("Status changed during collection")
                            record = normalize(row, datetime.now(UTC))
                            if record:
                                records.append(("ipos", record))
                                try:
                                    premium = normalize_gmp(row)
                                    if premium:
                                        records.append(("gmp", premium))
                                except (ValueError, TypeError, KeyError):
                                    errors.append((f"gmp:{key}", "IPOALERTS_INVALID_GMP"))
                        except ValidationError as exc:
                            # Field paths/types are actionable without exposing raw values.
                            fields = ",".join(
                                ".".join(map(str, item["loc"])) + ":" + item["type"]
                                for item in exc.errors(include_input=False, include_context=False)[
                                    :3
                                ]
                            )
                            errors.append((f"ipos:{key}:{fields}"[:200], "IPOALERTS_INVALID_ROW"))
                        except (ValueError, TypeError, KeyError, AttributeError) as exc:
                            errors.append(
                                (
                                    f"ipos:{key}:mapping:{type(exc).__name__}",
                                    "IPOALERTS_INVALID_ROW",
                                )
                            )
                    pages.append(IPOBatch(URL, raw, records, errors))
                    if page >= meta["totalPages"]:
                        if len(seen) != meta["count"]:
                            raise FeedError("IPOALERTS_PAGINATION_CHANGED")
                        for batch in pages:
                            yield batch
                        break
                else:
                    raise FeedError("IPOALERTS_PAGE_LIMIT")
