import pytest

from packages.shared.screener import canonical_screener_url, screener_url


@pytest.mark.parametrize("field", ["return_ipo", "drawdown"])
@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_sort_before_pagination(client, field, order):
    base = f"/api/v1/tracker?sort={field}&order={order}"
    items = (await client.get(base + "&page_size=100")).json()["items"]
    expected = sorted(
        items,
        key=lambda c: (
            c[field] is None,
            (c[field] if order == "asc" else -c[field]) if c[field] is not None else 0,
            c["name"].casefold(),
            str(c["id"]),
        ),
    )
    assert items == expected
    page = (await client.get(base + "&page_size=2&page=2")).json()["items"]
    assert [c["id"] for c in page] == [c["id"] for c in expected[2:4]]
    assert (await client.get("/api/v1/tracker?sort=bad")).status_code == 422


def test_screener_identity_and_validation():
    assert (
        screener_url(None, [("BSE", "544975"), ("NSE", "DOVE")])
        == "https://www.screener.in/company/544975/consolidated/"
    )
    assert screener_url(None, [("BSE_ISSUE", "544975"), ("BSE_SYMBOL", "DOVE")]) is None
    assert (
        screener_url(None, [("NSE", "M&M")])
        == "https://www.screener.in/company/M%26M/consolidated/"
    )
    explicit = "https://www.screener.in/company/EXAMPLE/"
    assert screener_url(explicit, [("BSE", "544975")]) == explicit
    for bad in [
        "javascript:alert(1)",
        "https://evil.com/company/544975/",
        "https://www.screener.in@evil.com/company/544975/",
        "https://www.screener.in/company/../",
    ]:
        assert canonical_screener_url(bad) is None


async def test_catalog_resolves_persisted_identifiers(client):
    items = (await client.get("/api/v1/tracker?page_size=100")).json()["items"]
    assert any(c["screener_url"] for c in items)
    for c in items:
        if c["screener_url"]:
            assert c["screener_url"].startswith("https://www.screener.in/company/")
