"""NSE consolidated (all exchanges) subscription table, verified against its public page."""

import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from packages.providers.bse_ipo import CATEGORIES, label
from packages.providers.market import FeedError, Subscriptions


def url(symbol):
    return "https://www.nseindia.com/api/ipo-active-category?" + urlencode({"symbol": symbol})


def parse(content, symbol, identity):
    raw = content.decode("utf-8-sig")
    try:
        body = json.loads(raw)
        rows = body["dataList"]
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError()
        if body.get("symbol") not in (None, "", symbol):
            raise ValueError()
        stamp = re.fullmatch(
            r"Updated as on (\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2})(?: hrs)?",
            body.get("updateTime", ""),
        )
        if not stamp:
            raise FeedError("NSE_SUBSCRIPTION_NOT_PUBLISHED", raw=raw)
        observed = datetime.strptime(stamp[1], "%d-%b-%Y %H:%M:%S").replace(
            tzinfo=ZoneInfo("Asia/Kolkata")
        )
        categories = {}
        for row in rows:
            key = CATEGORIES.get(label(row["category"]))
            if not key:
                continue  # Do not add constituent subcategories to their parent totals.
            if key in categories:
                raise ValueError()

            def number(field, row=row):
                value = str(row.get(field, "")).replace(",", "").strip()
                return None if value in ("", "-", "None") else Decimal(value)

            offered, bids, multiple = (
                number("noOfShareOffered"),
                number("noOfSharesBid"),
                number("noOfTotalMeant"),
            )
            categories[key] = {
                "offered_shares": offered,
                "bid_shares": bids,
                "multiple": None
                if offered == 0 or multiple is None
                else multiple.quantize(Decimal("0.0001")),
            }
        record = Subscriptions(
            **identity, source_url=url(symbol), source_timestamp=observed, categories=categories
        )
        return raw, [("subscriptions", record.model_dump(mode="json"))], []
    except FeedError:
        raise
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise FeedError("NSE_SUBSCRIPTION_SCHEMA_CHANGED", raw=raw) from None
