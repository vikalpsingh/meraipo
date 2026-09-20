"""Bounded exchange downloads and explicit source parsers. Never bypass access controls."""

import asyncio
import copy
import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, TypeAdapter, field_validator

from packages.providers.market import Eod, FeedError, Issue, Subscriptions

VERSION = "exchange-v1"
HOSTS = {
    "www.nseindia.com",
    "nsearchives.nseindia.com",
    "archives.nseindia.com",
    "www.bseindia.com",
    "api.bseindia.com",
}
NSE_IPO = "https://www.nseindia.com/api/ipo-current-issue"
NSE_UPCOMING = "https://www.nseindia.com/api/ipo-upcoming-issue"


def exchange_url(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in HOSTS
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise FeedError("UNAPPROVED_EXCHANGE_URL")
    return url


async def download(url, *, transport=None):
    exchange_url(url)
    async with (
        asyncio.timeout(22),
        httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=5), follow_redirects=False, transport=transport
        ) as client,
    ):
        try:
            async with client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "MeraIPO/1.0 (+scheduled end-of-day research)",
                    "Accept": "application/json,text/csv,application/zip,application/xml",
                },
            ) as response:
                if response.status_code != 200:
                    raise FeedError(f"EXCHANGE_HTTP_{response.status_code}")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 20_000_000:
                        raise FeedError("EXCHANGE_FILE_TOO_LARGE")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise FeedError("EXCHANGE_UNAVAILABLE") from exc


def bhavcopy_url(exchange, day):
    root = (
        "https://nsearchives.nseindia.com/content/cm"
        if exchange == "NSE"
        else "https://www.bseindia.com/download/BhavCopy/Equity"
    )
    return (
        f"{root}/BhavCopy_{exchange}_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
        if exchange == "NSE"
        else f"{root}/BhavCopy_{exchange}_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV"
    )


def csv_text(content):
    if content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                files = [f for f in archive.infolist() if f.filename.lower().endswith(".csv")]
                if len(files) != 1 or files[0].file_size > 40_000_000:
                    raise FeedError("UNSAFE_BHAVCOPY_ARCHIVE")
                content = archive.read(files[0])
        except zipfile.BadZipFile as exc:
            raise FeedError("INVALID_BHAVCOPY_ARCHIVE") from exc
    if len(content) > 40_000_000:
        raise FeedError("EXCHANGE_FILE_TOO_LARGE")
    return content.decode("utf-8-sig")


def parse_bhavcopy(content, exchange, day, identities, fetched_at):
    """One bulk file, exact identifiers only; malformed tracked rows are isolated."""
    raw = csv_text(content)
    rows = csv.DictReader(io.StringIO(raw))
    required = {
        "TradDt",
        "ISIN",
        "ClsPric",
        "OpnPric",
        "HghPric",
        "LwPric",
        "PrvsClsgPric",
        "TtlTradgVol",
        "TtlTrfVal",
    }
    if not required.issubset(rows.fieldnames or []):
        raise FeedError("UDIFF_SCHEMA_CHANGED", raw=raw)
    records, errors = [], []
    for index, row in enumerate(rows):
        if index > 100000:
            raise FeedError("TOO_MANY_EXCHANGE_ROWS")
        isin, symbol, code = (
            row.get("ISIN", "").strip(),
            row.get("TckrSymb", "").strip(),
            row.get("FinInstrmId", "").strip(),
        )
        if (
            isin not in identities["isin"]
            and (symbol if exchange == "NSE" else code) not in identities[exchange]
        ):
            continue
        if exchange == "NSE" and row.get("SctySrs") not in (None, "", "EQ", "SM", "ST", "BE", "BZ"):
            continue
        try:
            if date.fromisoformat(row["TradDt"].split("T")[0]) != day:
                raise FeedError("WRONG_TRADE_DATE")
            values = {
                key: row[source].strip() or None
                for key, source in {
                    "close": "ClsPric",
                    "open": "OpnPric",
                    "high": "HghPric",
                    "low": "LwPric",
                    "previous_close": "PrvsClsgPric",
                    "volume": "TtlTradgVol",
                    "turnover": "TtlTrfVal",
                }.items()
            }
            # A zero previous close on a listing day means unavailable, not a real quote.
            for key in ("open", "high", "low", "previous_close"):
                if values[key] and Decimal(values[key]) == 0:
                    values[key] = None
            record = Eod(
                isin=isin or None,
                nse_symbol=symbol or None if exchange == "NSE" else None,
                bse_code=code or None if exchange == "BSE" else None,
                price_date=day,
                source_url=bhavcopy_url(exchange, day),
                source_timestamp=fetched_at,
                **values,
            )
            records.append(("prices", record.model_dump(mode="json")))
        except Exception as exc:
            errors.append(
                (str(index), str(exc) if isinstance(exc, FeedError) else "INVALID_PRICE_ROW")
            )
    return raw, records, errors


def parse_date(value):
    if not value or value == "-":
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise FeedError("INVALID_EXCHANGE_DATE")


def parse_nse_ipos(content, fetched_at, upcoming=False):
    raw = content.decode("utf-8-sig")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise FeedError("NSE_IPO_SCHEMA_CHANGED", raw=raw) from exc
    if not isinstance(body, list) or len(body) > 1000:
        raise FeedError("NSE_IPO_SCHEMA_CHANGED", raw=raw)
    records, errors = [], []
    url = NSE_UPCOMING if upcoming else NSE_IPO
    for index, row in enumerate(body):
        try:
            if str(row.get("isBse", "")) == "1":
                raise FeedError("BSE_IDENTIFIER_REQUIRED")
            symbol, name = row["symbol"], row["companyName"]
            opened, closed = parse_date(row.get("issueStartDate")), parse_date(
                row.get("issueEndDate")
            )
            day = fetched_at.astimezone(ZoneInfo("Asia/Kolkata")).date()
            status = (
                "UPCOMING"
                if upcoming or (opened and opened > day)
                else "CLOSED" if closed and closed < day else "OPEN"
            )
            band = re.findall(r"\d+(?:\.\d+)?", str(row.get("issuePrice", "")).replace(",", ""))
            prices = {"price_low": band[0], "price_high": band[-1]} if 1 <= len(band) <= 2 else {}
            # Exchange-provided symbol is a mapping key, never derived from company names.
            identity = {"nse_symbol": symbol}
            issue = Issue(
                **identity,
                source_url=url,
                source_timestamp=fetched_at,
                official_status=status,
                issue={
                    "slug": "nse-" + re.sub(r"[^a-z0-9]+", "-", symbol.lower()).strip("-"),
                    "name": name,
                    "sector": "Not classified",
                    "board": "SME" if row.get("series") in ("SME", "SM") else "Mainboard",
                    "status": status,
                    "provider": "NSE",
                    "source_url": url,
                    "source_timestamp": fetched_at,
                    "open_date": opened,
                    "close_date": closed,
                    **prices,
                },
            )
            records.append(("ipos", issue.model_dump(mode="json")))
            categories = {}
            if row.get("noOfTime") not in (None, "", "-"):
                categories["total"] = {
                    "multiple": str(Decimal(str(row["noOfTime"])).quantize(Decimal("0.0001"))),
                    "bid_shares": row.get("noOfsharesBid"),
                    "offered_shares": row.get("noOfSharesOffered"),
                }
            if categories:
                subscription = Subscriptions(
                    **identity, source_url=url, source_timestamp=fetched_at, categories=categories
                )
                records.append(("subscriptions", subscription.model_dump(mode="json")))
        except Exception as exc:
            errors.append(
                (str(index), str(exc) if isinstance(exc, FeedError) else "INVALID_IPO_ROW")
            )
    return raw, records, errors


class DiscoverySource(BaseModel):
    """Reviewed native field names, not a paid intermediary feed contract."""

    name: str = Field(max_length=80)
    exchange: Literal["NSE", "BSE"]
    kind: Literal["ipos", "results", "subscriptions"]
    url: str
    records_path: str = "data"
    fields: dict[str, str]
    defaults: dict = Field(default_factory=dict)
    concepts: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    page_param: str | None = None
    page_size: int = Field(default=100, ge=1, le=500)
    size_param: str = "size"
    _url = field_validator("url")(exchange_url)


def discovery_sources(value):
    return TypeAdapter(list[DiscoverySource]).validate_json(value or "[]")


def discovery_url(source, start, end, page=1):
    params = {
        key: value.replace("{from}", start.strftime("%d-%m-%Y")).replace(
            "{to}", end.strftime("%d-%m-%Y")
        )
        for key, value in source.params.items()
    }
    if source.page_param:
        params.update({source.page_param: str(page), source.size_param: str(source.page_size)})
    return source.url + ("&" if "?" in source.url else "?") + urlencode(params)


def discovery_rows(content, source):
    body = json.loads(content)
    for key in filter(None, source.records_path.split(".")):
        body = body[key]
    if not isinstance(body, list) or len(body) > 5000:
        raise FeedError("DISCOVERY_SCHEMA_CHANGED")
    return body


def mapped_row(row, source):
    result = copy.deepcopy(source.defaults)
    for target, field in source.fields.items():
        value = row
        for key in field.split("."):
            value = value[key]
        destination = result
        keys = target.split(".")
        for key in keys[:-1]:
            destination = destination.setdefault(key, {})
        destination[keys[-1]] = value
    return result


def source_timestamp(value):
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            result = None
            for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    result = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    pass
            if result is None:
                raise FeedError("INVALID_FILING_TIMESTAMP") from None
    return result if result.tzinfo else result.replace(tzinfo=ZoneInfo("Asia/Kolkata"))


def financial_records(xml, metadata, concepts):
    """Only complete fiscal duration contexts; retain both bases and annual periods."""
    from xml.etree import ElementTree as ET

    from packages.providers.market import Financial
    from packages.providers.xbrl import NS, parse_instance

    if not concepts:
        raise FeedError("XBRL_TAXONOMY_NOT_CONFIGURED")
    if len(xml.encode()) > 2_000_000 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise FeedError("UNSAFE_XBRL")
    root = ET.fromstring(xml)
    if root.tag != "{http://www.xbrl.org/2003/instance}xbrl":
        raise FeedError("XBRL_INSTANCE_REQUIRED")
    results = []
    for context in root.findall("x:context", NS):
        start = context.findtext("x:period/x:startDate", namespaces=NS)
        end = context.findtext("x:period/x:endDate", namespaces=NS)
        if not start or not end:
            continue
        identifier = context.findtext("x:entity/x:identifier", namespaces=NS)
        if metadata.get("isin") and identifier != metadata["isin"]:
            raise FeedError("XBRL_COMPANY_MISMATCH")
        start, end = date.fromisoformat(start), date.fromisoformat(end)
        days = (end - start).days + 1
        if not (89 <= days <= 92 or 365 <= days <= 366):
            continue
        members = context.findall(".//d:explicitMember", NS)
        if context.findall(".//d:typedMember", NS) or len(members) > 1:
            continue
        member = (members[0].text or "").split(":")[-1].lower() if members else "standalone"
        if member not in ("consolidatedmember", "standalonemember", "consolidated", "standalone"):
            continue
        basis = "CONSOLIDATED" if member.startswith("consolidated") else "STANDALONE"
        parsed = parse_instance(xml, context.get("id"), concepts, basis)
        quarterly = days < 100
        values = {
            **metadata,
            "period_type": "QUARTERLY" if quarterly else "ANNUAL",
            "statement_type": basis,
            "period_start": start,
            "period_end": end,
            "financial_year": end.year + (end.month > 3),
            "quarter": (end.month - 4) % 12 // 3 + 1 if quarterly else None,
        }
        from apps.api.schemas import Metrics

        values["industry_metrics"] = {}
        for key, value in parsed["metrics"].items():
            if key in Metrics.model_fields:
                values[key] = value
            else:
                values["industry_metrics"][key] = value
        results.append(Financial.model_validate(values).model_dump(mode="json"))
    if not results:
        raise FeedError("NO_DISCRETE_FINANCIAL_CONTEXT")
    # Duplicate period/basis contexts are ambiguous even if each individual context is valid.
    keys = [(r["period_start"], r["period_end"], r["statement_type"]) for r in results]
    if len(keys) != len(set(keys)):
        raise FeedError("AMBIGUOUS_FINANCIAL_CONTEXTS")
    return results
