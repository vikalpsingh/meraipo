"""Bounded results HTTP sessions with stage-specific, credential-free evidence."""

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from packages.providers.exchanges import exchange_url
from packages.providers.market import FeedError

LANDINGS = {
    "BSE": "https://www.bseindia.com/corporates/comp_results",
    "NSE": "https://www.nseindia.com/companies-listing/corporate-integrated-filing",
}
# Request compatibility checked against bse 3.3.3; no runtime dependency added.
BSE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"


def safe_url(value):
    p = urlsplit(str(value))
    return urlunsplit((p.scheme, p.hostname or "", p.path, "", ""))[:1000]


def excerpt(value):
    value = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(
        r"(?i)(cookie|authorization|token|secret|api[-_]?key|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(r"https?://\S+", lambda m: safe_url(m[0]), value)
    value = re.sub(r"\b[A-Za-z0-9_+/=-]{32,}\b", "[redacted]", value)
    return " ".join(value.split())[:400]


class SourceError(FeedError):
    def __init__(self, code, retry_at=None, diagnostic=None):
        super().__init__(code)
        self.retry_at = retry_at
        self.diagnostic = diagnostic


class ExchangeSession:
    def __init__(self, exchange, transport=None):
        self.exchange, self.events = exchange, []
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
            headers={
                "User-Agent": BSE_UA
                if exchange == "BSE"
                else "Mozilla/5.0 (compatible; MeraIPO/1.0)",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": LANDINGS[exchange],
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def initialize(self):
        try:
            await self.get(LANDINGS[self.exchange], landing=True)
        except SourceError:
            # A browser shell is not a prerequisite for BSE's ordinary API.
            if self.exchange != "BSE":
                raise

    async def request_target(self, url):
        exchange_url(url)
        headers = {}
        if self.exchange == "BSE":
            headers = {
                "Origin": "https://www.bseindia.com",
                "Sec-Fetch-Site": "same-site"
                if urlsplit(url).hostname == "api.bseindia.com"
                else "same-origin",
            }
        return url, headers, {}

    async def get(self, url, landing=False, stage=None):
        stage = stage or (
            "session_initialization"
            if landing
            else "results_list"
            if "NSTodayResults" in url or "integrated-filing-results" in url
            else "company_announcements"
            if "AnnSubCategory" in url
            else "result_detail"
            if "Corp_Finance" in url
            else "attachment_download"
        )
        for attempt in range(2):
            started, chain = time.monotonic(), []
            evidence = {"stage": stage, "url": safe_url(url), "status": None, "redirects": chain}
            try:
                for redirect in range(6):
                    target, headers, extensions = await self.request_target(url)
                    async with self.client.stream(
                        "GET", target, headers=headers, extensions=extensions
                    ) as response:
                        evidence.update(
                            url=safe_url(url),
                            status=response.status_code,
                            content_type=response.headers.get("content-type", "")[:120],
                            references={
                                k: excerpt(response.headers[k])
                                for k in (
                                    "x-request-id",
                                    "x-correlation-id",
                                    "cf-ray",
                                    "x-amz-cf-id",
                                )
                                if k in response.headers
                            },
                        )
                        if response.is_redirect:
                            chain.append({"status": response.status_code, "url": safe_url(url)})
                            url = urljoin(url, response.headers.get("location", ""))
                            if redirect == 5:
                                raise SourceError("SOURCE_REDIRECT_LIMIT")
                            continue
                        data = bytearray()
                        async for part in response.aiter_bytes():
                            data.extend(part)
                            if response.status_code != 200 and len(data) >= 2000:
                                break
                            if len(data) > 10_000_000:
                                raise SourceError("SOURCE_FILE_TOO_LARGE")
                        if response.status_code != 200:
                            evidence["excerpt"] = excerpt(
                                bytes(data[:2000]).decode("utf-8", errors="replace")
                            )
                            if response.status_code == 429:
                                value = response.headers.get("retry-after", "60")
                                try:
                                    retry = datetime.now(timezone.utc) + timedelta(
                                        seconds=max(0, int(value))
                                    )
                                except ValueError:
                                    try:
                                        retry = parsedate_to_datetime(value)
                                    except (TypeError, ValueError):
                                        retry = datetime.now(timezone.utc) + timedelta(minutes=5)
                                raise SourceError("SOURCE_RATE_LIMITED", retry)
                            raise SourceError(f"SOURCE_HTTP_{response.status_code}")
                        if not landing and b"access denied" in bytes(data[:1000]).lower():
                            evidence["excerpt"] = excerpt(
                                bytes(data[:2000]).decode("utf-8", errors="replace")
                            )
                            raise SourceError("SOURCE_BLOCK_PAGE")
                        evidence.update(
                            code="SUCCESS", elapsed_ms=round((time.monotonic() - started) * 1000)
                        )
                        self.events.append(evidence)
                        return bytes(data)
            except (httpx.HTTPError, FeedError) as exc:
                code = (
                    "SOURCE_TIMEOUT"
                    if isinstance(exc, httpx.TimeoutException)
                    else "SOURCE_UNAVAILABLE"
                    if isinstance(exc, httpx.HTTPError)
                    else str(exc)
                )
                evidence.update(code=code, elapsed_ms=round((time.monotonic() - started) * 1000))
                self.events.append(evidence)
                # No retries of access denials or throttling.
                if attempt == 0 and (
                    isinstance(exc, httpx.TransportError) or code.startswith("SOURCE_HTTP_5")
                ):
                    await asyncio.sleep(0.3)
                    continue
                raise SourceError(code, getattr(exc, "retry_at", None), evidence) from exc
        raise SourceError("SOURCE_UNAVAILABLE")
