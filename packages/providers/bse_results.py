"""BSE corporate announcements: bounded complete pagination and original links."""

import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from packages.providers.exchanges import exchange_url
from packages.providers.result_http import SourceError

ANNOUNCEMENTS = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"


def attachment_url(row):
    value = row.get("ATTACHMENTNAME")
    if not value:
        return None
    # Preserve returned full/relative paths. Bare names use the announcement archive flag.
    if value.startswith(("https://", "/")):
        return exchange_url(urljoin("https://www.bseindia.com/", value))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:pdf|xml|xbrl|xlsx|xls)", value, re.I):
        raise SourceError("SOURCE_ATTACHMENT_LINK_REVIEW")
    folder = "AttachHis" if str(row.get("OLD")) == "1" else "AttachLive"
    return exchange_url(f"https://www.bseindia.com/xml-data/corpfiling/{folder}/{value}")


def is_result(row):
    category = str(row.get("CATEGORYNAME") or "").casefold()
    text = " ".join(str(row.get(k) or "") for k in ("SUBCATNAME", "NEWSSUB")).casefold()
    if "intimation" in text or "board meeting" in text and "outcome" not in text:
        return False
    return (
        category in ("result", "results")
        or "financial results" in text
        or "integrated filing" in text
        and "financial" in text
    )


async def discover(session, code, start, end):
    found, seen, expected = [], set(), None
    for page in range(1, 101):
        params = dict(
            pageno=page,
            strCat="-1",
            subcategory="-1",
            strPrevDate=start.strftime("%Y%m%d"),
            strToDate=end.strftime("%Y%m%d"),
            strSearch="P",
            strscrip=code,
            strType="C",
        )
        url = ANNOUNCEMENTS + "?" + urlencode(params)
        content = await session.get(url)
        try:
            body = json.loads(content)
            rows, total = body["Table"], int(body["Table1"][0]["ROWCNT"])
            if not isinstance(rows, list) or total < 0:
                raise ValueError()
            if expected is not None and expected != total:
                raise SourceError("SOURCE_PAGINATION_CHANGED")
            expected = total
            for row in rows:
                key = str(row["NEWSID"])
                if key in seen or str(row["SCRIP_CD"]) != code:
                    raise SourceError("SOURCE_INCOMPLETE_DISCOVERY")
                seen.add(key)
                if not is_result(row):
                    continue
                url_attachment = attachment_url(row)
                stamp = datetime.fromisoformat(row["DT_TM"])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                found.append(
                    {
                        "identifier": code,
                        "filing_id": key,
                        "announced_at": stamp.isoformat(),
                        "attachments": [url_attachment] if url_attachment else [],
                        "source_url": ANNOUNCEMENTS,
                        # Stable fields exclude changing RN/OLD/archive location from identity.
                        "subject": row.get("NEWSSUB"),
                        "category": row.get("CATEGORYNAME"),
                        "attachment_name": row.get("ATTACHMENTNAME"),
                    }
                )
            if len(seen) == total:
                return found
            if not rows or len(seen) > total:
                raise SourceError("SOURCE_INCOMPLETE_DISCOVERY")
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise SourceError("SOURCE_INVALID_DISCOVERY") from exc
    raise SourceError("SOURCE_PAGE_LIMIT")
