"""Resolve outbound research links from persisted company identities, never names."""

import re
from urllib.parse import quote, unquote, urlsplit


def canonical_screener_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value.strip())
        if url.scheme != "https" or url.netloc.lower() not in ("screener.in", "www.screener.in"):
            return None
        path = unquote(url.path)
        if not re.fullmatch(r"/company/[A-Za-z0-9&._-]+/(?:consolidated/)?", path):
            return None
        if path.split("/")[2] in (".", ".."):
            return None
        return "https://www.screener.in" + quote(path, safe="/&.-_")
    except ValueError:
        return None


def screener_url(explicit, identifiers):
    supplied = canonical_screener_url(explicit)
    if supplied:
        return supplied
    for exchange in ("BSE", "NSE"):
        for kind, ticker in sorted(identifiers):
            pattern = r"[0-9]{6}" if exchange == "BSE" else r"[A-Z0-9][A-Z0-9&._-]{0,39}"
            if kind == exchange and re.fullmatch(pattern, ticker):
                return (
                    "https://www.screener.in/company/" + quote(ticker, safe="") + "/consolidated/"
                )
    return None
