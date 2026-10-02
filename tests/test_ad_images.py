import hashlib

import httpx
import pytest

from apps.api.ad_images import LogoError, downloadable_url, fetch_logo

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'
STYLED_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><defs><style>.brand{fill:#f6461a}</style></defs><path class="brand" d="M0 0h1v1z"/></svg>'


def test_wikimedia_file_page_resolves_to_original_file():
    assert downloadable_url("https://commons.wikimedia.org/wiki/File:Zerodha_Kite_logo.svg") == (
        "https://commons.wikimedia.org/wiki/Special:Redirect/file/Zerodha_Kite_logo.svg"
    )


async def test_fetch_logo_follows_redirect_and_validates_svg():
    def handler(request: httpx.Request):
        if request.url.host == "commons.wikimedia.org":
            return httpx.Response(
                302,
                headers={"location": "https://upload.wikimedia.org/wikipedia/commons/kite.svg"},
            )
        return httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=SVG)

    logo = await fetch_logo(
        "https://commons.wikimedia.org/wiki/File:Zerodha_Kite_logo.svg",
        transport=httpx.MockTransport(handler),
    )
    assert logo.content == SVG
    assert logo.mime == "image/svg+xml"
    assert logo.sha256 == hashlib.sha256(SVG).hexdigest()


async def test_fetch_logo_accepts_self_contained_svg_styles():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"content-type": "image/svg+xml"}, content=STYLED_SVG
        )
    )
    logo = await fetch_logo("https://example.com/logo.svg", transport=transport)
    assert logo.content == STYLED_SVG


@pytest.mark.parametrize(
    ("content_type", "content", "message"),
    [
        ("text/html", b"<html></html>", "supported image"),
        ("image/png", b"not-a-png", "Invalid PNG"),
        ("image/svg+xml", b"<svg><script/></svg>", "Unsafe SVG"),
        (
            "image/svg+xml",
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x.png"/></svg>',
            "Unsafe SVG",
        ),
        (
            "image/svg+xml",
            b'<svg xmlns="http://www.w3.org/2000/svg"><style>.x{fill:url(https://example.com/x)}</style></svg>',
            "Unsafe SVG style",
        ),
    ],
)
async def test_fetch_logo_rejects_invalid_content(content_type, content, message):
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"content-type": content_type}, content=content
        )
    )
    with pytest.raises(LogoError, match=message):
        await fetch_logo("https://example.com/logo", transport=transport)


async def test_fetch_logo_rejects_oversized_file():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n" + b"x" * 1_000_000,
        )
    )
    with pytest.raises(LogoError, match="1 MB"):
        await fetch_logo("https://example.com/logo.png", transport=transport)
