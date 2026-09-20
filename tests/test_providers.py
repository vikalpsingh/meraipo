import pytest
from sqlalchemy import func, select

from apps.worker.ingestion import ingest
from packages.database.models import GMP, IPO, Company, QualityIssue
from packages.providers.adapters import FixtureProvider, ManualProvider, provider
from packages.providers.contracts import Batch
from packages.providers.storage import LocalStorage


async def test_eod_price_snapshot_and_conflicting_retry(db):
    from datetime import date
    from decimal import Decimal

    from packages.database.models import Price, PriceSnapshot

    company = await db.scalar(select(Company).where(Company.slug == "aarya-energy"))
    record = {
        "company_slug": company.slug,
        "price_date": date.today().isoformat(),
        "close": 125,
        "high": 130,
        "low": 120,
        "source_url": "https://example.com/price",
    }
    assert (await ingest(db, Batch("fixture", "price-1", "prices", [record]), "price-run-1"))[
        "status"
    ] == "SUCCEEDED"
    snapshot = await db.scalar(select(PriceSnapshot).where(PriceSnapshot.company_id == company.id))
    assert snapshot.cmp == Decimal("125") and snapshot.ath >= Decimal("130")
    before = await db.scalar(select(func.count()).select_from(Price))
    changed = {**record, "close": 126}
    assert (await ingest(db, Batch("fixture", "price-2", "prices", [changed]), "price-run-2"))[
        "status"
    ] == "CONFLICT"
    assert (await db.scalar(select(func.count()).select_from(Price))) == before
    assert snapshot.cmp == Decimal("125")


async def test_document_ingestion_deduplicates(db):
    from packages.database.models import Document

    before = await db.scalar(select(func.count()).select_from(Document))
    records = [
        {
            "company_slug": "aarya-energy",
            "kind": "RHP",
            "source_url": "https://example.com/new-rhp.pdf",
        }
    ]
    for key in ("docs-run-1", "docs-run-2"):
        await ingest(db, Batch("fixture", key, "documents", records), key)
    assert (await db.scalar(select(func.count()).select_from(Document))) == before + 1


async def test_manual_and_fixture_contracts():
    assert (await ManualProvider().fetch("prices")).records == []
    assert (await FixtureProvider({"ipos": [{"slug": "a"}]}).fetch("ipos")).records == [
        {"slug": "a"}
    ]
    with pytest.raises(ValueError):
        provider("unlicensed-live")


async def test_ingestion_idempotency(db):
    before = await db.scalar(select(func.count()).select_from(GMP))
    batch = Batch(
        "fixture",
        "request-1",
        "gmp",
        [
            {
                "company_slug": "aarya-energy",
                "value": 23,
                "observed_at": "2026-01-01T12:00:00Z",
                "source_url": "https://example.com",
                "import_key": "ingestion-fixture-key",
            }
        ],
    )
    assert (await ingest(db, batch, "run-one"))["duplicate"] is False
    assert (await ingest(db, batch, "run-one"))["duplicate"] is True
    assert (await db.scalar(select(func.count()).select_from(GMP))) == before + 1


async def test_conflicting_import_does_not_overwrite(db):
    batch = Batch(
        "fixture",
        "request-2",
        "ipos",
        [
            {
                "slug": "aarya-energy",
                "name": "Aarya Energy",
                "sector": "Technology",
                "status": "OPEN",
                "price_high": 999,
                "source_url": "https://example.com",
            }
        ],
    )
    assert (await ingest(db, batch, "conflict-run"))["status"] == "CONFLICT"
    ipo = await db.scalar(select(IPO).join(Company).where(Company.slug == "aarya-energy"))
    assert ipo.price_high == 150
    assert (await db.scalar(select(func.count()).select_from(QualityIssue))) == 1


def test_storage_rejects_traversal_and_invalid_uploads(tmp_path):
    storage = LocalStorage(str(tmp_path))
    key = storage.put(b"%PDF-1.7\nfixture", "application/pdf")
    assert storage.get(key).startswith(b"%PDF-")
    with pytest.raises(ValueError):
        storage.get("../private.txt")
    with pytest.raises(ValueError):
        storage.put(b"html", "application/pdf")
    with pytest.raises(ValueError):
        storage.put(b"%PDF-" + b"x" * (10 * 1024 * 1024), "application/pdf")
