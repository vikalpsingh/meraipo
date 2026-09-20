"""Explicit, idempotent demo fixture loader. Never run in production."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from apps.api.schemas import GMPInput, IPOInput, QuarterInput
from apps.api.services import add_gmp, add_quarter, maintain_ipo
from packages.database import models as m
from packages.database.session import Session
from packages.shared.config import settings


async def seed(db):
    if settings().environment == "production" or not settings().demo_mode:
        raise RuntimeError("Demo seed requires DEMO_MODE=true outside production")
    names = [
        "Aarya Energy",
        "Nimbus Logistics",
        "Terra Health",
        "Neel Water",
        "Cedar Foods",
        "Nava Mobility",
        "Prava Technologies",
        "Vedant Consumer",
        "Orion Components",
        "Megha Systems",
        "Savera Pharma",
        "Aranya Solar",
        "Kavya Retail",
        "Delta Packaging",
        "Pine Logistics",
        "Sutra Finance",
        "Kiran Materials",
    ]
    today = date.today()
    for i, name in enumerate(names):
        slug = name.lower().replace(" ", "-")
        if await db.scalar(select(m.Company).where(m.Company.slug == slug)):
            continue
        status = "OPEN" if i < 3 else "UPCOMING" if i < 6 else "CLOSED" if i == 16 else "LISTED"
        listed = status == "LISTED"
        listing_day = (
            today - timedelta(days=(i - 5) * 18) if listed else today + timedelta(days=12 + i)
        )
        if status == "OPEN":
            listing_day = today + timedelta(days=9 + i)
        elif status == "CLOSED":
            listing_day = today + timedelta(days=2)
        if listed and i < 12:
            listing_day = date(2024, 4, 10) + timedelta(days=i - 6)
        price = Decimal(150 + i * 15)
        missing = i == 4
        data = IPOInput(
            slug=slug,
            name=name,
            sector=["Technology", "Industrials", "Consumer", "Healthcare"][i % 4],
            board="SME" if i % 5 == 4 else "Mainboard",
            ticker=f"DEMO{i:02}",
            status=status,
            open_date=listing_day - timedelta(days=12),
            close_date=listing_day - timedelta(days=9),
            listing_date=listing_day,
            price_low=None if missing else price - 10,
            price_high=None if missing else price,
            issue_price=price if listed else None,
            listing_price=price * Decimal("1.12") if listed else None,
            lot_size=None if missing else 50,
            issue_size=650 + i * 40,
            fresh_issue=500 + i * 30,
            ofs=150 + i * 10,
            source_url="https://example.com/demo-fixture",
            provider="demo",
            verification_status="UNVERIFIED",
            baseline=(
                {
                    "revenue": 460,
                    "ebitda": 46,
                    "pat": 25,
                    "eps": 2.5,
                    "debt": 120,
                    "cfo": 30,
                    "roe": 12,
                    "roce": 14,
                }
                if listed
                else None
            ),
            baseline_pe=23 if listed else None,
            baseline_market_cap=1200 if listed else None,
        )
        company = await maintain_ipo(db, data, None)
        company.is_demo = True
        ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
        if company.board == "Mainboard":
            db.add(
                m.ApplicantGuide(
                    ipo_id=ipo.id,
                    category="Retail individual",
                    min_lots=1,
                    max_amount=200000,
                    allotment_date=listing_day - timedelta(days=2),
                    unblock_date=listing_day - timedelta(days=1),
                    schedule_status="TENTATIVE",
                    business_summary=f"{name} is a fictional {data.sector.lower()} business used to demonstrate IPO research. This is not an investment opportunity.",
                    strengths="Example: recurring customer demand\nExample: improving operating capacity\nExample: established distribution",
                    risks="Example: dependence on major customers\nExample: input-cost fluctuations\nExample: execution risk on expansion",
                    proceeds="Illustrative use: expand operations, reduce borrowings and fund working capital. Verify actual allocations in a real issue's prospectus.",
                    source_url="https://example.com/demo-fixture",
                    reviewed_on=today,
                    verification_status="UNVERIFIED",
                )
            )
        if not missing:
            for day in range(3):
                await add_gmp(
                    db,
                    slug,
                    GMPInput(
                        value=12 + i + day,
                        observed_at=m.now() - timedelta(hours=2 + day * 8),
                        source_url="https://example.com/demo-gmp",
                        provider="demo",
                        import_key=f"demo-gmp-{i}-{day}",
                    ),
                )
        if listed:
            if i < 12:
                for q in range(6):
                    revenue = Decimal(300 + q * 40 + max(0, q - 3) * 50 + i * 3)
                    pat = Decimal(20 + q * 5 + max(0, q - 3) * 8)
                    if i % 3 == 2:
                        revenue = Decimal(600 - q * 20)
                        pat = Decimal(60 - q * 5)
                    await add_quarter(
                        db,
                        slug,
                        QuarterInput(
                            financial_year=2025 + q // 4,
                            quarter=q % 4 + 1,
                            revenue=revenue,
                            ebitda=revenue * (Decimal("0.12") + q * Decimal("0.005")),
                            pat=pat,
                            eps=pat / 10,
                            debt=120 - q * 8,
                            cfo=pat + 8,
                            roe=12 + q,
                            roce=14 + q,
                            source_url="https://example.com/demo-results",
                            provider="demo",
                            import_key=f"demo-quarter-{i}-{q}",
                        ),
                    )
            cmp = price * Decimal("1.45" if i % 3 == 0 else "0.85" if i % 3 == 1 else "1.08")
            db.add(
                m.PriceSnapshot(
                    company_id=company.id,
                    cmp=cmp,
                    ath=cmp * Decimal("1.4"),
                    high_52w=cmp * Decimal("1.4"),
                    low_52w=price * Decimal("0.8"),
                    price_date=today,
                )
            )
            for offset in (365, 180, 90, 30, 0):
                db.add(
                    m.Price(
                        company_id=company.id,
                        price_date=today - timedelta(days=offset),
                        close=cmp * (Decimal("1") - Decimal(offset) / 2000),
                        high=cmp * Decimal("1.02"),
                        low=cmp * Decimal(".98"),
                        source_url="https://example.com/demo-eod",
                    )
                )
            db.add(
                m.Valuation(
                    company_id=company.id,
                    as_of=today,
                    pe=24 + i,
                    peer_median_pe=30,
                    market_cap=2500 + i * 100,
                )
            )
    if not await db.scalar(select(m.SiteMessage).limit(1)):
        db.add(
            m.SiteMessage(
                title="A thought for the long term",
                content="A listing lasts a day. A business earns your attention quarter after quarter.",
                attribution="MeraIPO editorial",
                kind="quote",
                enabled=True,
            )
        )
    await db.commit()


async def main():
    async with Session() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
