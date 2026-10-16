"""IPOWEB: official exchange discovery plus the trading app's IPOWatch source."""

import asyncio
import hashlib
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx

from packages.providers import exchanges
from packages.providers.bse_ipo import BSE_LIST_URL, parse_issues
from packages.providers.ipo import IPOBatch
from packages.providers.market import FeedError, Issue

WATCH_URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
SOURCES = ("nse", "bse", "ipowatch")


def company_key(name):
    name = re.sub(r"\b(limited|ltd|private|pvt)\b\.?", "", name.casefold())
    return re.sub(r"[^a-z0-9]", "", name)


class WatchTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
        self.heading, self.title, self.board = False, [], "Unknown"
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3"):
            self.heading, self.title = True, []
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.link = [], None
        elif tag == "a" and self.cell is not None:
            self.link = dict(attrs).get("href")

    def handle_data(self, value):
        if self.heading:
            self.title.append(value)
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ("h2", "h3"):
            title = " ".join(self.title).lower()
            self.board = (
                "SME" if "sme" in title else "Mainboard" if "mainboard" in title else "Unknown"
            )
            self.heading = False
        if tag in ("td", "th") and self.cell is not None:
            self.row.append((" ".join(" ".join(self.cell).split()), self.link))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.board, self.row))
            self.row = None
            if len(self.rows) > 500:
                raise FeedError("IPOWEB_TOO_MANY_ROWS")


def dates(value, today):
    if value.strip().lower() in (
        "",
        "-",
        "na",
        "n/a",
        "tba",
        "to be announced",
        "dates awaited",
        "upcoming",
    ):
        return None, None
    value = value.replace("–", "-").replace("—", "-")
    match = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?", value)
    if match:
        month = datetime.strptime(match[3][:3], "%b").month
        year = int(match[4] or today.year)
        if not match[4] and today.month == 12 and month == 1:
            year += 1
        elif not match[4] and today.month == 1 and month == 12:
            year -= 1
        opened, closed = date(year, month, int(match[1])), date(year, month, int(match[2]))
    else:
        parts = re.split(r"\s+-\s+", value)
        if len(parts) != 2:
            raise ValueError("Unrecognized date range")
        opened, closed = (datetime.strptime(p, "%d %b %Y").date() for p in parts)
    if closed < opened:
        raise ValueError("Reversed dates")
    return opened, closed


def parse_watch(content, observed_at):
    raw = content.decode("utf-8-sig")
    parser = WatchTables()
    parser.feed(raw)
    columns, records, errors, seen = None, [], [], set()
    today = observed_at.astimezone(ZoneInfo("Asia/Kolkata")).date()
    for board, cells in parser.rows:
        labels = [re.sub(r"[^a-z]", "", c[0].lower()) for c in cells]
        if "company" in labels and "date" in labels and "priceband" in labels:
            columns = {key: labels.index(key) for key in ("company", "date", "priceband")}
            for key in ("lotsize", "issuesizecrore"):
                if key in labels:
                    columns[key] = labels.index(key)
            continue
        if not columns or len(cells) <= max(columns.values()):
            continue
        try:
            company, href = cells[columns["company"]]
            name = re.sub(r"\s+(?:Upcoming|Open|Closed|\(C\))$", "", company, flags=re.I).strip()
            if not name or not href:
                raise ValueError("Company link missing")
            url = urljoin(WATCH_URL, href)
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.netloc != "ipowatch.in"
                or parts.query
                or parts.fragment
                or "ipo" not in parts.path
            ):
                raise ValueError("Unrecognized company link")
            opened, closed = dates(cells[columns["date"]][0], today)
            key = (company_key(name), opened)
            if key in seen:
                continue
            band = cells[columns["priceband"]][0].replace("₹", "").replace(",", "").strip()
            low = high = None
            if band.lower() not in ("", "-", "na", "n/a", "tba"):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?", band)
                if not match:
                    raise ValueError("Unrecognized price band")
                low, high = Decimal(match[1]), Decimal(match[2] or match[1])
            status = (
                "ANNOUNCED"
                if not opened
                else "UPCOMING"
                if opened > today
                else "CLOSED"
                if closed < today
                else "OPEN"
            )
            identity = hashlib.sha256(parts.path.encode()).hexdigest()[:32]
            extra = {}
            for column, field in (("lotsize", "lot_size"), ("issuesizecrore", "issue_size")):
                if column in columns:
                    text = cells[columns[column]][0].replace(",", "").replace("₹", "").strip()
                    if text.lower() not in ("", "-", "n/a", "na", "tba"):
                        if not re.fullmatch(r"\d+(?:\.\d+)?", text):
                            raise ValueError("Invalid numeric column")
                        extra[field] = Decimal(text)
            record = Issue(
                provider_namespace="IPOWEB",
                provider_id=identity,
                source_url=url,
                source_timestamp=observed_at,
                official_status=status,
                issue=dict(
                    slug="ipoweb-" + identity,
                    name=name,
                    sector="Unclassified",
                    board=board,
                    status="UPCOMING" if status == "ANNOUNCED" else status,
                    open_date=opened,
                    close_date=closed,
                    price_low=low,
                    price_high=high,
                    source_url=url,
                    **extra,
                ),
            )
            seen.add(key)
            records.append(("ipos", record.model_dump(mode="json")))
            if len(records) > 100:
                raise FeedError("IPOWEB_TOO_MANY_ROWS")
        except (ValueError, TypeError):
            errors.append((f"ipowatch:row-{len(seen)}", "IPOWEB_INVALID_ROW"))
    if not records:
        raise FeedError("IPOWEB_SCHEMA_CHANGED")
    return raw, records, errors


async def download_watch():
    async with (
        asyncio.timeout(25),
        httpx.AsyncClient(
            timeout=12,
            follow_redirects=False,
            headers={"User-Agent": "MeraIPO/1.0", "Accept": "text/html"},
        ) as client,
    ):
        robots = await client.get("https://ipowatch.in/robots.txt")
        if robots.status_code != 200:
            raise FeedError("IPOWEB_ROBOTS_UNAVAILABLE")
        policy = RobotFileParser()
        policy.parse(robots.text.splitlines())
        if not policy.can_fetch("MeraIPO", WATCH_URL):
            raise FeedError("IPOWEB_ACCESS_DISALLOWED")
        async with client.stream("GET", WATCH_URL) as response:
            if response.status_code != 200:
                raise FeedError(f"IPOWEB_HTTP_{response.status_code}")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 3_000_000:
                    raise FeedError("IPOWEB_PAYLOAD_TOO_LARGE")
                chunks.append(chunk)
            return b"".join(chunks)


class IPOWeb:
    name, authority = "IPOWEB", "UNOFFICIAL"

    def __init__(self, sources=SOURCES, fetch=exchanges.download, watch_fetch=download_watch):
        self.sources, self.fetch, self.watch_fetch = sources, fetch, watch_fetch

    async def batches(self, deadline):
        for source, url, parser in (
            ("nse", exchanges.NSE_IPO, exchanges.parse_nse_ipos),
            (
                "nse",
                exchanges.NSE_UPCOMING,
                lambda data, now: exchanges.parse_nse_ipos(data, now, True),
            ),
            ("bse", BSE_LIST_URL, parse_issues),
            ("ipowatch", WATCH_URL, parse_watch),
        ):
            if source not in self.sources:
                continue
            if time.monotonic() >= deadline:
                raise FeedError("IPOWEB_TIME_BUDGET")
            try:
                content = (
                    await self.watch_fetch() if source == "ipowatch" else await self.fetch(url)
                )
                raw, records, errors = parser(content, datetime.now(UTC))
                if source != "ipowatch":
                    for kind, value in records:
                        if kind == "ipos":
                            identity = (
                                value.get("nse_symbol")
                                or value.get("bse_symbol")
                                or value.get("bse_issue_id")
                                or value.get("bse_code")
                            )
                            value["provider_namespace"] = "IPOWEB"
                            value["provider_id"] = hashlib.sha256(
                                f"{source}:{identity}".encode()
                            ).hexdigest()[:32]
                yield IPOBatch(
                    url,
                    raw,
                    [(k, v) for k, v in records if k == "ipos"],
                    errors,
                    "UNOFFICIAL" if source == "ipowatch" else source.upper(),
                )
            except Exception as exc:
                code = str(exc) if isinstance(exc, FeedError) else "IPOWEB_SOURCE_UNAVAILABLE"
                yield IPOBatch(url, "", [], [(source, code)])
