"""Verified exchange discovery and conservative, versioned financial XBRL parsing."""

import asyncio
import csv
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx

from packages.providers.exchanges import exchange_url, source_timestamp
from packages.providers.market import FeedError

VERSION = "results-2026.1"
LANDINGS = {
    "BSE": "https://www.bseindia.com/corporates/comp_results",
    "NSE": "https://www.nseindia.com/companies-listing/corporate-integrated-filing",
}
BSE_TODAY = "https://api.bseindia.com/BseIndiaAPI/api/NSTodayResults_Download/w"
BSE_HISTORY = "https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng_new/w"
NSE_RESULTS = "https://www.nseindia.com/api/integrated-filing-results"
X = "{http://www.xbrl.org/2003/instance}"
D = "{http://xbrl.org/2006/xbrldi}"
TAXONOMY = "http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt"
CONCEPTS = {
    "revenue": "RevenueFromOperations",
    "total_income": "Income",
    "pbt": "ProfitBeforeTax",
    "pat": "ProfitLossForPeriod",
    "pat_owners": "ProfitOrLossAttributableToOwnersOfParent",
    "basic_eps": "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "diluted_eps": "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
}


class SourceError(FeedError):
    def __init__(self, code, retry_at=None):
        super().__init__(code)
        self.retry_at = retry_at


class ExchangeSession:
    def __init__(self, exchange, transport=None):
        self.exchange = exchange
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(18, connect=5),
            follow_redirects=False,
            transport=transport,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MeraIPO/1.0)",
                "Accept": "application/json,text/csv,application/xml,text/html",
                "Referer": LANDINGS[exchange],
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def initialize(self):
        await self.get(LANDINGS[self.exchange], landing=True)

    async def get(self, url, landing=False):
        for attempt in range(2):
            try:
                for redirect in range(6):
                    exchange_url(url)
                    async with self.client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            if redirect == 5:
                                raise SourceError("SOURCE_REDIRECT_LIMIT")
                            continue
                        if response.status_code in (403, 406):
                            raise SourceError("SOURCE_ACCESS_BLOCKED")
                        if response.status_code == 429:
                            value = response.headers.get("retry-after", "60")
                            try:
                                retry = datetime.now(timezone.utc) + timedelta(seconds=int(value))
                            except ValueError:
                                try:
                                    retry = parsedate_to_datetime(value)
                                except ValueError:
                                    retry = datetime.now(timezone.utc) + timedelta(minutes=5)
                            raise SourceError("SOURCE_RATE_LIMITED", retry)
                        if response.status_code == 401 and not landing and attempt == 0:
                            await self.initialize()
                            break
                        if response.status_code >= 500 and attempt == 0:
                            break
                        if response.status_code != 200:
                            raise SourceError(f"SOURCE_HTTP_{response.status_code}")
                        data = bytearray()
                        async for part in response.aiter_bytes():
                            data.extend(part)
                            if len(data) > 10_000_000:
                                raise SourceError("SOURCE_FILE_TOO_LARGE")
                        if not landing and b"access denied" in bytes(data[:1000]).lower():
                            raise SourceError("SOURCE_ACCESS_BLOCKED")
                        return bytes(data)
            except httpx.HTTPError as exc:
                if attempt:
                    raise SourceError("SOURCE_UNAVAILABLE") from exc
            await asyncio.sleep(0.3)
        raise SourceError("SOURCE_UNAVAILABLE")


def bse_csv(content):
    text = content.decode("utf-8-sig")
    if re.search(r"<\s*(?:html|!doctype)", text, re.I):
        raise SourceError("SOURCE_INVALID_DISCOVERY")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(v.strip() for v in row):
            continue
        if not rows and row[0].strip().lower().replace("_", " ") in (
            "scrip code",
            "scripcode",
            "scrip cd",
            "security code",
        ):
            continue
        if len(row) != 5 or not re.fullmatch(r"[0-9]{6}", row[0].strip()):
            raise SourceError("SOURCE_INVALID_DISCOVERY")
        code, name, reporting, audit, announced = [v.strip() for v in row]
        try:
            stamp = datetime.strptime(announced, "%b %d %Y %I:%M%p").replace(
                tzinfo=ZoneInfo("Asia/Kolkata")
            )
        except ValueError as exc:
            raise SourceError("SOURCE_INVALID_DISCOVERY") from exc
        rows.append(
            {
                "identifier": code,
                "name": name,
                "reporting_code": reporting,
                "audit": audit,
                "announced_at": stamp.isoformat(),
                "attachments": [],
                "source_url": BSE_TODAY,
            }
        )
    if not rows:
        raise SourceError("SOURCE_EMPTY_UNVERIFIED")
    return rows


def nse_rows(content):
    try:
        body = json.loads(content)
        rows, count = body["data"], int(body["totalCount"])
        if not isinstance(rows, list) or count < len(rows) or count < 0:
            raise ValueError()
        result = []
        for row in rows:
            attachments = []
            for key in ("xbrl", "ixbrl", "pdf_attach"):
                value = row.get(key)
                if value and not value.endswith("/null"):
                    attachments.append(exchange_url(value))
            result.append(
                {
                    "identifier": row["symbol"],
                    "filing_id": str(row["seq_Id"]),
                    "announced_at": source_timestamp(
                        row.get("revised_Date") or row["creation_Date"]
                    ).isoformat(),
                    "basis": row["consolidated"].upper(),
                    "period_end": datetime.strptime(row["qe_Date"], "%d-%b-%Y").date().isoformat(),
                    "attachments": attachments,
                    "raw": row,
                    "source_url": NSE_RESULTS,
                }
            )
        return result, count
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError("SOURCE_INVALID_DISCOVERY") from exc


async def discover_nse(session, start, end, symbol=None):
    result = []
    for board in ("equities", "sme"):
        seen = set()
        expected = None
        for page in range(1, 501):
            params = {
                "type": "Integrated Filing- Financials",
                "page": page,
                "size": 100,
                "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y"),
            }
            if board == "sme":
                params["index"] = "sme"
            if symbol:
                params["symbol"] = symbol
            rows, total = nse_rows(await session.get(NSE_RESULTS + "?" + urlencode(params)))
            if expected is not None and expected != total:
                raise SourceError("SOURCE_PAGINATION_CHANGED")
            expected = total
            keys = {row["filing_id"] for row in rows}
            if seen & keys or (not rows and len(seen) < total):
                raise SourceError("SOURCE_INCOMPLETE_DISCOVERY")
            seen.update(keys)
            result.extend(rows)
            if len(seen) >= total:
                break
        else:
            raise SourceError("SOURCE_PAGE_LIMIT")
    return result


async def discover_bse_history(session, code):
    # Parameters and actual attachment paths observed in BSE's own results module.
    params = {"SCRIP_CD": code, "FlagDur": "7", "HFQ": "", "ISUBGROUP_CODE": "", "segment": "C"}
    content = await session.get(BSE_HISTORY + "?" + urlencode(params))
    try:
        rows = json.loads(content)["Table"]
        if not isinstance(rows, list):
            raise ValueError()
        result = []
        for row in rows:
            for key, basis in (("XMLName", "STANDALONE"), ("Consol_XMLName", "CONSOLIDATED")):
                if row.get(key):
                    result.append(
                        {
                            "identifier": str(row["Scrip_cd"]),
                            "basis": basis,
                            "attachments": [
                                exchange_url(
                                    urljoin("https://www.bseindia.com/XBRLFILES/", row[key])
                                )
                            ],
                            "raw": row,
                            "source_url": BSE_HISTORY,
                        }
                    )
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError("SOURCE_INVALID_DISCOVERY") from exc


def attachment_type(content):
    if not content or len(content) > 10_000_000:
        raise SourceError("INVALID_ATTACHMENT_SIZE")
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if (
                    "xl/workbook.xml" not in archive.namelist()
                    or sum(f.file_size for f in archive.infolist()) > 30_000_000
                ):
                    raise SourceError("UNSUPPORTED_ATTACHMENT_REVIEW")
        except zipfile.BadZipFile as exc:
            raise SourceError("UNSUPPORTED_ATTACHMENT_REVIEW") from exc
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "application/vnd.ms-excel"
    if b"http://www.xbrl.org/2013/inlineXBRL" in content and b"<html" in content.lower():
        return "application/xhtml+xml"  # retained as download only; never executed or guessed into metrics
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise SourceError("UNSAFE_XML")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceError("UNSUPPORTED_ATTACHMENT_REVIEW") from exc
    if root.tag == X + "xbrl":
        return "application/xml"
    if any("http://www.xbrl.org/2013/inlineXBRL" in el.tag for el in root.iter()):
        return "application/xhtml+xml"
    raise SourceError("UNSUPPORTED_ATTACHMENT_REVIEW")


def parse_xbrl(content, identifiers, expected_basis=None, expected_end=None):
    if attachment_type(content) != "application/xml":
        raise SourceError("PARSING_REVIEW_REQUIRED")
    root = ET.fromstring(content)
    # Only this observed, versioned industrial taxonomy has been verified.
    if not any(el.tag.startswith("{" + TAXONOMY + "}") for el in root):
        raise SourceError("TAXONOMY_REVIEW_REQUIRED")
    namespaces = {}
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(content), events=["start-ns"]):
        if prefix in namespaces and namespaces[prefix] != uri:
            raise SourceError("NAMESPACE_REDEFINITION_REVIEW")
        namespaces[prefix] = uri
    entry = namespaces.get("in-capmkt-ent", "")
    templates = {
        f"http://www.sebi.gov.in/xbrl/{template}/2026-01-31/in-capmkt/in-capmkt-ent"
        for template in ("IntegratedFinance_IndAS", "IntegratedFinance_OtherThanBank")
    }
    if entry not in templates:
        raise SourceError("SECTOR_TEMPLATE_REVIEW_REQUIRED")
    concepts = dict(CONCEPTS)
    if "IntegratedFinance_OtherThanBank" in entry:
        concepts["pat"] = "ProfitLossForPeriodBeforeMinorityInterest"
    q = "{" + TAXONOMY + "}"

    def fact(name, context=None):
        items = [
            el
            for el in root.findall(q + name)
            if context is None or el.get("contextRef") == context
        ]
        if len(items) > 1:
            values = {el.text for el in items}
            if context is not None or len(values) > 1:
                raise SourceError("AMBIGUOUS_FINANCIAL_FACT")
        return items[0] if items else None

    def value(name):
        el = fact(name)
        return el.text.strip() if el is not None and el.text else None

    matched = False
    for key, tag in (("BSE", "ScripCode"), ("NSE", "Symbol"), ("ISIN", "ISIN")):
        observed = value(tag)
        if observed and identifiers.get(key):
            if observed not in identifiers[key]:
                raise SourceError("FILING_COMPANY_MISMATCH")
            matched = True
    if not matched:
        raise SourceError("FILING_IDENTITY_REQUIRED")
    basis = (value("NatureOfReportStandaloneConsolidated") or "").upper()
    if basis not in ("STANDALONE", "CONSOLIDATED") or (expected_basis and basis != expected_basis):
        raise SourceError("FILING_BASIS_MISMATCH")
    expected_end = expected_end or value("DateOfEndOfReportingPeriod")
    if not expected_end:
        raise SourceError("REPORTING_PERIOD_REVIEW_REQUIRED")
    units = {el.get("id"): el for el in root.findall(X + "unit")}
    contexts = root.findall(X + "context")
    if len(units) != len(root.findall(X + "unit")) or len({c.get("id") for c in contexts}) != len(
        contexts
    ):
        raise SourceError("DUPLICATE_CONTEXT_OR_UNIT")
    output = []
    for context in root.findall(X + "context"):
        if context.findall(".//" + D + "explicitMember") or context.findall(
            ".//" + D + "typedMember"
        ):
            continue
        identity = context.findtext(X + "entity/" + X + "identifier")
        if identity not in set().union(*identifiers.values()):
            raise SourceError("CONTEXT_COMPANY_MISMATCH")
        start = context.findtext(X + "period/" + X + "startDate")
        end = context.findtext(X + "period/" + X + "endDate")
        if not start or not end:
            continue
        if expected_end and end != expected_end:
            continue  # Comparative facts remain in the retained original, not silently restated.
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        days = (end_date - start_date).days + 1
        period = next(
            (
                label
                for low, high, label in (
                    (89, 92, "QUARTERLY"),
                    (181, 184, "HALF_YEARLY"),
                    (273, 276, "NINE_MONTH"),
                    (365, 366, "ANNUAL"),
                )
                if low <= days <= high
            ),
            None,
        )
        if period is None:
            continue
        values, original = {}, {}
        for metric, tag in concepts.items():
            el = fact(tag, context.get("id"))
            if el is None or el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in (
                "true",
                "1",
            ):
                values[metric] = None
                continue
            unit = units.get(el.get("unitRef"))
            if unit is None:
                raise SourceError("FINANCIAL_UNIT_REQUIRED")
            measures = [e.text or "" for e in unit.findall(".//" + X + "measure")]
            expanded = []
            for measure in measures:
                prefix, local = measure.split(":") if ":" in measure else ("", measure)
                expanded.append((namespaces.get(prefix), local))
            eps = metric.endswith("eps")
            expected = [("http://www.xbrl.org/2003/iso4217", "INR")]
            if eps:
                expected.append(("http://www.xbrl.org/2003/instance", "shares"))
            if expanded != expected or (unit.find(X + "divide") is not None) != eps:
                raise SourceError("FINANCIAL_UNIT_REVIEW_REQUIRED")
            number = Decimal(el.text or "")
            if not number.is_finite() or el.get("scale") is not None:
                raise SourceError("FINANCIAL_SCALE_REVIEW_REQUIRED")
            # XBRL INR facts are already absolute rupees. LevelOfRounding and decimals are display/precision, not multipliers.
            values[metric] = str(number)
            original[metric] = {
                "value": el.text,
                "unit": el.get("unitRef"),
                "decimals": el.get("decimals"),
                "context": context.get("id"),
                "concept": el.tag,
            }
        if not any(v is not None for v in values.values()):
            continue
        output.append(
            {
                "period_start": start,
                "period_end": end,
                "period_type": period,
                "basis": basis,
                "facts": values,
                "original": original,
            }
        )
    keys = [(r["period_start"], r["period_end"], r["basis"]) for r in output]
    if len(keys) != len(set(keys)):
        raise SourceError("AMBIGUOUS_FINANCIAL_CONTEXT")
    if not output:
        raise SourceError("NO_SUPPORTED_FINANCIAL_CONTEXT")
    return output
