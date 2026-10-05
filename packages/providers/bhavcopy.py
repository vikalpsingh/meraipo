"""Strict UDiFF cash equity ingestion. No legacy routes or access-control workarounds."""

import asyncio
import csv
import io
import json
import re
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath

import httpx
from pydantic import BaseModel, Field, field_validator

from packages.providers.exchanges import exchange_url
from packages.providers.market import FeedError

MAX_DOWNLOAD = 20_000_000
MAX_CSV = 40_000_000


class RateLimited(FeedError):
    def __init__(self, delay):
        super().__init__("RATE_LIMITED_RETRY_LATER")
        self.retry_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, delay))


BSE_URL_TEMPLATE = (
    "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date}_F_0000.CSV"
)


def build_bse_url(trading_date: date) -> str:
    return BSE_URL_TEMPLATE.format(date=trading_date.strftime("%Y%m%d"))


PRICE_FIELDS = {
    "open": "OpnPric",
    "high": "HghPric",
    "low": "LwPric",
    "close": "ClsPric",
    "previous_close": "PrvsClsgPric",
    "volume": "TtlTradgVol",
}


class Source(BaseModel):
    enabled: bool = False
    url_template: str = ""
    verified_on: date | None = None
    public_display_allowed: bool = False
    calendar_year: int = Field(0, ge=0, le=2100)
    holidays: list[date] = Field(default_factory=list)
    special_sessions: list[date] = Field(default_factory=list)
    calendar_source: str = ""

    @field_validator("url_template")
    @classmethod
    def valid_url(cls, value):
        if value:
            exchange_url(value.replace("{yyyymmdd}", "20261001"))
            if value.count("{yyyymmdd}") != 1:
                raise ValueError("Use exactly one {yyyymmdd} placeholder")
        return value


def sources(value):
    data = json.loads(value or "{}")
    if not isinstance(data, dict) or set(data) - {"NSE", "BSE"}:
        raise ValueError("Configure NSE and/or BSE objects")
    return {exchange: Source.model_validate(data.get(exchange, {})) for exchange in ("NSE", "BSE")}


def trading_session(day, source):
    if source.calendar_year != day.year or not source.calendar_source:
        raise FeedError("TRADING_CALENDAR_REQUIRED")
    return day in source.special_sessions or (day.weekday() < 5 and day not in source.holidays)


def source_url(exchange, day, source):
    if not source.url_template or not source.verified_on:
        raise FeedError("SOURCE_CONFIGURATION_REQUIRED")
    url = exchange_url(source.url_template.replace("{yyyymmdd}", day.strftime("%Y%m%d")))
    from urllib.parse import urlsplit

    if not urlsplit(url).hostname.endswith("nseindia.com" if exchange == "NSE" else "bseindia.com"):
        raise FeedError("WRONG_SOURCE_EXCHANGE")
    return url


async def download(url, *, transport=None, sleep=asyncio.sleep):
    exchange_url(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25, connect=5), follow_redirects=False, transport=transport
    ) as client:
        for attempt in range(3):
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": "MeraIPO/1.0", "Accept": "application/zip,text/csv"},
                ) as response:
                    status = response.status_code
                    if status in (401, 403, 406) or 300 <= status < 400:
                        raise FeedError("SOURCE_ACCESS_BLOCKED")
                    if status in (404, 410):
                        raise FeedError("NOT_YET_PUBLISHED")
                    if status == 429:
                        retry = response.headers.get("Retry-After", "60")
                        try:
                            delay = float(retry)
                        except ValueError:
                            try:
                                delay = (
                                    parsedate_to_datetime(retry) - datetime.now(timezone.utc)
                                ).total_seconds()
                            except (ValueError, TypeError):
                                delay = 60
                        # Do not retry earlier than requested; defer long waits to scheduled retry.
                        if delay > 10 or attempt == 2:
                            raise RateLimited(delay)
                        await sleep(max(delay, 0))
                        continue
                    if status >= 500:
                        if attempt == 2:
                            raise FeedError("SOURCE_UNAVAILABLE")
                        await sleep(2**attempt)
                        continue
                    if status != 200:
                        raise FeedError(f"SOURCE_HTTP_{status}")
                    chunks, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_DOWNLOAD:
                            raise FeedError("DOWNLOAD_TOO_LARGE")
                        chunks.append(part)
                    content = b"".join(chunks)
                    if not content or "html" in response.headers.get("content-type", "").lower():
                        raise FeedError("INVALID_BHAVCOPY_CONTENT")
                    return content
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise FeedError("SOURCE_UNAVAILABLE") from exc
                await sleep(2**attempt)
    raise FeedError("SOURCE_UNAVAILABLE")


def csv_content(content):
    if not content or len(content) > MAX_DOWNLOAD:
        raise FeedError("INVALID_BHAVCOPY_SIZE")
    if content.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) != 1:
                    raise FeedError("UNSAFE_BHAVCOPY_ARCHIVE")
                member = members[0]
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or ":" in member.filename
                    or not member.filename.lower().endswith(".csv")
                    or member.flag_bits & 1
                    or member.file_size > MAX_CSV
                    or member.is_dir()
                ):
                    raise FeedError("UNSAFE_BHAVCOPY_ARCHIVE")
                with archive.open(member) as stream:
                    content = stream.read(MAX_CSV + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise FeedError("INVALID_BHAVCOPY_ARCHIVE") from exc
    if len(content) > MAX_CSV:
        raise FeedError("CSV_TOO_LARGE")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FeedError("UNSUPPORTED_BHAVCOPY_ENCODING") from exc
    if not text.strip() or text.lstrip().startswith("<") or "\x00" in text:
        raise FeedError("INVALID_BHAVCOPY_CONTENT")
    return text


def parse(content, exchange, day):
    """Validate the entire file's date/exchange before considering tracked securities."""
    reader = csv.DictReader(io.StringIO(csv_content(content)))
    required = {
        "TradDt",
        "Src",
        "Sgmt",
        "FinInstrmId",
        "ISIN",
        "TckrSymb",
        "SctySrs",
        "FinInstrmTp",
        "SsnId",
        *PRICE_FIELDS.values(),
    }
    if not required.issubset(reader.fieldnames or []) or len(reader.fieldnames) != len(
        set(reader.fieldnames)
    ):
        raise FeedError("UDIFF_SCHEMA_CHANGED")
    records, errors = [], []
    count = 0
    for count, row in enumerate(reader, 1):
        if count > 100000:
            raise FeedError("TOO_MANY_EXCHANGE_ROWS")
        if None in row or any(v is None for v in row.values()):
            raise FeedError("MALFORMED_CSV_ROW")
        row = {k: v.strip() for k, v in row.items()}
        # ISO dates (including ISO midnight timestamps) are the supported UDiFF form.
        try:
            actual = datetime.fromisoformat(row["TradDt"]).date()
        except ValueError as exc:
            raise FeedError("INVALID_TRADE_DATE") from exc
        if actual != day:
            raise FeedError("WRONG_TRADE_DATE")
        if row["Src"] != exchange or row["Sgmt"] != "CM":
            raise FeedError("WRONG_EXCHANGE_OR_SEGMENT")
        identity = {
            "isin": row["ISIN"],
            "symbol": row["TckrSymb"],
            "security_id": row["FinInstrmId"],
            "series": row["SctySrs"],
            "line": count + 1,
        }
        try:
            if row["FinInstrmTp"] != "STK" or row["SsnId"] != "F1":
                raise ValueError("UNSUPPORTED_INSTRUMENT_OR_SESSION")
            if not re.fullmatch(r"IN[A-Z0-9]{10}", identity["isin"]) or not identity["security_id"]:
                raise ValueError("INVALID_SECURITY_IDENTIFIER")
            if exchange == "NSE" and identity["series"] not in {"EQ", "BE", "BZ", "SM", "ST", "SZ"}:
                continue
            values = {}
            for key, field in PRICE_FIELDS.items():
                number = Decimal(row[field]) if row[field] else None
                if number is not None and (
                    not number.is_finite() or number < 0 or number >= Decimal("1e16")
                ):
                    raise ValueError("INVALID_PRICE")
                if key != "volume" and number == 0:
                    number = None
                if number is not None and number.as_tuple().exponent < (
                    -4 if key != "volume" else 0
                ):
                    raise ValueError("INVALID_PRECISION")
                values[key] = number
            if values["close"] is None:
                raise ValueError("MISSING_CLOSE")
            for key in ("open", "close"):
                n = values[key]
                if n is not None and (
                    (values["low"] is not None and n < values["low"])
                    or (values["high"] is not None and n > values["high"])
                ):
                    raise ValueError("INVALID_PRICE_RANGE")
            records.append({**identity, **values})
        except (ValueError, InvalidOperation) as exc:
            errors.append({**identity, "code": str(exc)[:100]})
    if count == 0:
        raise FeedError("EMPTY_BHAVCOPY")
    # Multiple series/session observations must never become last-row-wins updates.
    duplicates = Counter(r["isin"] for r in records + errors)
    accepted = []
    for row in records:
        if duplicates[row["isin"]] > 1:
            errors.append(
                {"line": row["line"], "isin": row["isin"], "code": "AMBIGUOUS_SECURITY_ROWS"}
            )
        else:
            accepted.append(row)
    return accepted, errors, count
