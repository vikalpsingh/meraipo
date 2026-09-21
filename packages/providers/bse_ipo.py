"""BSE cumulative-demand HTML adapter; explicit IPO IDs, never name-based joins."""

import json
import re
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from pydantic import Field, TypeAdapter

from packages.providers.exchanges import download, parse_date
from packages.providers.market import FeedError, Identity, Issue, Subscriptions

BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/GetPublicIssue_par_updated/w?flag=1"


def issue_date(value):
    if not isinstance(value, str) or not value.strip():
        raise FeedError("BSE_ISSUE_DATE_REQUIRED")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return parse_date(value)


def parse_issues(content, observed_at):
    """Field bindings verified in BSE's official IPO component; never scrape guessed columns.

    The public-issues feed also contains rights/OFS/debt, which must not become IPOs.
    API availability and the exact live payload remain separately verifiable at runtime.
    """
    raw = content.decode("utf-8-sig")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise FeedError("BSE_IPO_SCHEMA_CHANGED", raw=raw) from exc
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("Table"), list)
        or len(body["Table"]) > 2000
    ):
        raise FeedError("BSE_IPO_SCHEMA_CHANGED", raw=raw)
    records, errors = [], []
    today = observed_at.astimezone(ZoneInfo("Asia/Kolkata")).date()
    for index, row in enumerate(body["Table"]):
        item = f"ipos:row-{index}"
        try:
            if not isinstance(row, dict):
                raise FeedError("BSE_INVALID_IPO_ROW")
            item = f"ipos:{row.get('IPO_NO', index)}:{row.get('Scrip_Name', '')}"[:200]
            kind = str(row.get("IR_FLAG_FULL", "")).strip().upper()
            flag = str(row.get("IR_flag", "")).strip().upper()
            if flag in {"OFS", "OTB", "R", "RIGHTS", "DEBT", "NCD", "FPO"}:
                continue
            if kind not in {
                "IPO",
                "INITIAL PUBLIC OFFER",
                "INITIAL PUBLIC OFFERING",
                "INITIAL PUBLIC OFFER (IPO)",
            }:
                raise FeedError("BSE_ISSUE_TYPE_UNVERIFIED")
            platform = str(row.get("eXCHANGE_PLATFORM", "")).strip().upper()
            if platform in {"SME", "BSE SME"}:
                board = "SME"
            elif platform in {"BSE", "MAINBOARD", "MAIN BOARD", "BSE MAINBOARD", "BSE MAIN BOARD"}:
                board = "Mainboard"
            else:
                raise FeedError("BSE_PLATFORM_UNVERIFIED")
            opened, closed = issue_date(row.get("Start_Dt")), issue_date(row.get("End_Dt"))
            if not opened or not closed or closed < opened:
                raise FeedError("BSE_INVALID_ISSUE_DATES")
            if str(row.get("Status", "")) not in {"L", "F", "H"}:
                raise FeedError("BSE_ISSUE_STATUS_UNVERIFIED")
            status = "UPCOMING" if opened > today else "CLOSED" if closed < today else "OPEN"
            identity = {"bse_issue_id": str(row["IPO_NO"])}
            symbol = str(row.get("Scrip_cd", "")).strip()
            if re.fullmatch(r"[0-9]{6}", symbol):
                identity["bse_code"] = symbol
            elif re.fullmatch(r"[A-Z][A-Z0-9&._-]{0,39}", symbol):
                identity["bse_symbol"] = symbol
            if row.get("ISIN"):
                identity["isin"] = row["ISIN"]
            band = str(row.get("Price_Band") or "").strip()
            prices = {}
            if band not in {"", "-"}:
                numbers = re.findall(r"\d+(?:\.\d+)?", band.replace(",", ""))
                if not 1 <= len(numbers) <= 2:
                    raise FeedError("BSE_INVALID_PRICE_BAND")
                prices = {"price_low": numbers[0], "price_high": numbers[-1]}
            issue = Issue(
                **identity,
                source_url=BSE_LIST_URL,
                source_timestamp=observed_at,
                official_status=status,
                issue={
                    "slug": "bse-issue-" + identity["bse_issue_id"],
                    "name": row["Scrip_Name"],
                    "sector": "Not classified",
                    "board": board,
                    "status": status,
                    "provider": "BSE",
                    "source_url": BSE_LIST_URL,
                    "source_timestamp": observed_at,
                    "open_date": opened,
                    "close_date": closed,
                    **prices,
                },
            )
            records.append(("ipos", issue.model_dump(mode="json")))
        except Exception as exc:
            errors.append((item, str(exc) if isinstance(exc, FeedError) else "BSE_INVALID_IPO_ROW"))
    return raw, records, errors


class BseIssue(Identity):
    issue_id: str = Field(pattern=r"^[0-9]{1,10}$")


def configuration(value):
    return TypeAdapter(list[BseIssue]).validate_json(value or "[]")


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            if len(self.rows) > 2000:
                raise FeedError("BSE_TOO_MANY_ROWS")


def label(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


CATEGORIES = {
    "qib": "qib",
    "qibs": "qib",
    "qualifiedinstitutionalbuyers": "qib",
    "qualifiedinstitutionalbuyersqibs": "qib",
    "nii": "nii",
    "niis": "nii",
    "noninstitutionalinvestors": "nii",
    "noninstitutionalinvestorsniis": "nii",
    "noninstitutionalbidders": "nii",
    "noninstitutionalbiddersniis": "nii",
    "bnii": "bnii",
    "snii": "snii",
    "retail": "retail",
    "retailindividualinvestors": "retail",
    "retailindividualbidders": "retail",
    "retailindividualinvestorsriis": "retail",
    "employee": "employee",
    "employees": "employee",
    "shareholder": "shareholder",
    "shareholders": "shareholder",
    "total": "total",
    "grandtotal": "total",
}


def number(value):
    value = value.replace(",", "").replace("×", "").rstrip("xX").strip()
    if value in ("", "-", "NA", "N.A."):
        return None
    return Decimal(value)


class BseIpoProvider:
    @staticmethod
    def url(issue_id):
        return f"https://www.bseindia.com/markets/publicIssues/CummDemandSchedule.aspx?ID={issue_id}&status=L"

    @staticmethod
    def parse(content, issue, observed_at):
        raw = content.decode("utf-8-sig")
        if "cumulative demand" not in " ".join(raw.lower().split()):
            raise FeedError("BSE_CUMULATIVE_PAGE_REQUIRED", raw=raw)
        parser = Tables()
        parser.feed(raw)
        columns, categories = None, {}
        for row in parser.rows:
            keys = [label(cell) for cell in row]
            if any("category" in key for key in keys):
                found = {}
                for i, key in enumerate(keys):
                    if "category" in key:
                        found["category"] = i
                    elif ("offered" in key or "reserved" in key) and "share" in key:
                        found["offered_shares"] = i
                    elif ("bid" in key or "received" in key) and (
                        "share" in key or "quantity" in key
                    ):
                        found["bid_shares"] = i
                    elif "subscription" in key or "times" in key:
                        found["multiple"] = i
                if {"category", "offered_shares", "bid_shares"} <= found.keys():
                    columns = found
                continue
            if not columns or len(row) <= max(columns.values()):
                continue
            category = CATEGORIES.get(label(row[columns["category"]]))
            if not category:
                continue
            if category in categories:
                raise FeedError("BSE_AMBIGUOUS_CATEGORY", raw=raw)
            categories[category] = {
                key: number(row[index]) for key, index in columns.items() if key != "category"
            }
        if not categories:
            raise FeedError("BSE_DEMAND_SCHEMA_CHANGED", raw=raw)
        result = Subscriptions(
            **issue.model_dump(exclude={"issue_id"}),
            source_url=BseIpoProvider.url(issue.issue_id),
            source_timestamp=observed_at,
            categories=categories,
        )
        return raw, [("subscriptions", result.model_dump(mode="json"))], []

    async def fetch(self, issue, observed_at, fetch=download):
        return self.parse(await fetch(self.url(issue.issue_id)), issue, observed_at)
