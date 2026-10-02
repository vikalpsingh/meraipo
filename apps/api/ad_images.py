"""Fetch small advertisement logos once and serve them from MeraIPO."""

import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx

MAX_IMAGE_BYTES = 1_000_000
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}


class LogoError(ValueError):
    pass


@dataclass(frozen=True)
class CachedLogo:
    content: bytes
    mime: str
    sha256: str


def downloadable_url(value: str) -> str:
    """Convert a Wikimedia file-description page to its original-file redirect."""
    parsed = urlsplit(value)
    if parsed.hostname == "commons.wikimedia.org" and parsed.path.startswith("/wiki/File:"):
        name = unquote(parsed.path.removeprefix("/wiki/File:"))
        if not name or "/" in name or "\\" in name:
            raise LogoError("Invalid Wikimedia file name")
        return "https://commons.wikimedia.org/wiki/Special:Redirect/file/" + quote(
            name, safe="._-()"
        )
    return value


async def public_https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise LogoError("Logo must use a public HTTPS URL")
    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise LogoError("Logo host could not be resolved") from exc
    for address in {item[4][0] for item in addresses}:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise LogoError("Logo host must resolve to a public address")
    return value


def validate_image(content: bytes, mime: str) -> None:
    if mime == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise LogoError("Invalid PNG logo")
    if mime == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise LogoError("Invalid JPEG logo")
    if mime == "image/gif" and not content.startswith((b"GIF87a", b"GIF89a")):
        raise LogoError("Invalid GIF logo")
    if mime == "image/webp" and not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        raise LogoError("Invalid WebP logo")
    if mime != "image/svg+xml":
        return
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise LogoError("Unsafe SVG declaration")
    try:
        root = ElementTree.fromstring(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ElementTree.ParseError) as exc:
        raise LogoError("Invalid SVG logo") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise LogoError("Invalid SVG root")
    forbidden = {"script", "foreignobject", "iframe", "object", "embed", "image"}
    for element in root.iter():
        element_name = element.tag.rsplit("}", 1)[-1].lower()
        if element_name in forbidden:
            raise LogoError("Unsafe SVG element")
        if element_name == "style":
            css = (element.text or "").lower()
            if any(token in css for token in ("url(", "@import", "expression(")):
                raise LogoError("Unsafe SVG style")
        for key, value in element.attrib.items():
            attribute = key.rsplit("}", 1)[-1].lower()
            lowered = value.strip().lower()
            if attribute.startswith("on") or "url(" in lowered:
                raise LogoError("Unsafe SVG attribute")
            if attribute == "href" and lowered and not lowered.startswith("#"):
                raise LogoError("External SVG references are not allowed")


async def fetch_logo(value: str, *, transport=None) -> CachedLogo:
    url = downloadable_url(value)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12, connect=4),
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "MeraIPO/1.0 (+advertisement-logo-cache)", "Accept": "image/*"},
    ) as client:
        for _ in range(5):
            if transport is None:
                await public_https_url(url)
            try:
                async with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise LogoError("Logo redirect has no destination")
                        url = str(response.url.join(location))
                        continue
                    if response.status_code != 200:
                        raise LogoError(f"Logo source returned HTTP {response.status_code}")
                    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if mime not in ALLOWED_MIME:
                        raise LogoError("URL did not return a supported image")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise LogoError("Logo exceeds the 1 MB limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    if not content:
                        raise LogoError("Logo is empty")
                    validate_image(content, mime)
                    return CachedLogo(content, mime, hashlib.sha256(content).hexdigest())
            except httpx.HTTPError as exc:
                raise LogoError("Logo could not be downloaded") from exc
    raise LogoError("Logo has too many redirects")
