"""Approved company IR pages; public HTTPS, exact origin, pinned DNS per request."""

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from packages.providers.result_http import ExchangeSession, SourceError


def approved_url(url, origin=None):
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443)
            or p.query or p.fragment or "\\" in unquote(p.path) or ".." in unquote(p.path).split("/")
            or origin and p.hostname != urlsplit(origin).hostname):
        raise SourceError("UNAPPROVED_COMPANY_SOURCE")
    try:
        if not ipaddress.ip_address(p.hostname).is_global:
            raise SourceError("UNAPPROVED_COMPANY_SOURCE")
    except ValueError:
        if "." not in p.hostname or p.hostname.endswith((".local", ".internal", ".localhost")):
            raise SourceError("UNAPPROVED_COMPANY_SOURCE") from None
    return url


async def public_address(url):
    approved_url(url)
    host = urlsplit(url).hostname
    addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = sorted({item[4][0] for item in addresses})
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise SourceError("UNAPPROVED_COMPANY_SOURCE")
    return ips[0]


class CompanySession(ExchangeSession):
    def __init__(self, page_url, document_prefix, transport=None):
        super().__init__("BSE", transport)
        self.page_url = approved_url(page_url)
        self.document_prefix = approved_url(document_prefix, page_url)
        self.client.headers.clear()
        self.client.headers.update({"User-Agent": "MeraIPO/1.0 (+official financial results)", "Accept": "text/html,application/xml,application/pdf,*/*"})

    async def request_target(self, url):
        approved_url(url, self.page_url)
        if url != self.page_url and not url.startswith(self.document_prefix):
            raise SourceError("UNAPPROVED_COMPANY_SOURCE")
        address = await public_address(url)
        host = urlsplit(url).hostname
        # Pin the validated public address; preserve TLS hostname verification and Host.
        return str(httpx.URL(url).copy_with(host=address)), {"Host": host}, {"sni_hostname": host}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            value = dict(attrs).get("href")
            if value:
                self.links.append(value)


async def discover(session):
    body = await session.get(session.page_url, landing=True, stage="official_company_discovery")
    parser = Links()
    parser.feed(body.decode("utf-8", errors="replace"))
    urls = set()
    for href in parser.links:
        url = urljoin(session.page_url, href)
        if url.startswith(session.document_prefix) and urlsplit(url).path.lower().endswith((".xml", ".xbrl", ".pdf", ".xlsx", ".xls")):
            approved_url(url, session.page_url)
            urls.add(url)
    return sorted(urls)[:30]
