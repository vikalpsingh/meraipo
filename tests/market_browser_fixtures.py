"""Fictional provider data, imported through the real normalization/persistence path."""

import calendar
from datetime import date

from apps.worker.market import ingest_record
from packages.database import models as m
from packages.providers.market import Eod, Financial, Premium, Subscriptions


async def seed_market_browser(db):
    general = m.Company(
        slug="integration-market-fixture",
        name="Integration Market Fixture",
        isin="INE000A02010",
        is_demo=True,
    )
    bank = m.Company(
        slug="integration-bank-fixture",
        name="Integration Bank Fixture",
        isin="INE000A03010",
        company_type="BANK",
        is_demo=True,
    )
    db.add_all([general, bank])
    await db.flush()
    for company in (general, bank):
        ipo = m.IPO(
            company_id=company.id,
            status="LISTED",
            issue_price=100,
            listing_price=110,
            price_high=100,
            lot_size=100,
        )
        db.add(ipo)
        await db.flush()
        db.add(m.IPODate(ipo_id=ipo.id, listing_date=date(2024, 1, 1)))
        db.add(
            m.Identifier(
                company_id=company.id,
                exchange="NSE",
                ticker="INTDATA" if company == general else "INTBANK",
            )
        )
    await db.flush()
    common = {
        "isin": general.isin,
        "source_url": "https://exchange.example/fictional-filing",
        "source_timestamp": "2026-07-20T10:00:00Z",
    }
    for index in range(10):
        absolute_month = 2024 * 12 + index * 3
        year, start_month = absolute_month // 12, absolute_month % 12 + 1
        end_month = start_month + 2
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        data = Financial.model_validate(
            {
                **common,
                "financial_year": end.year + (end.month > 3),
                "quarter": (end.month - 4) % 12 // 3 + 1,
                "period_type": "QUARTERLY",
                "statement_type": "CONSOLIDATED",
                "period_start": date(year, start_month, 1),
                "period_end": end,
                "filing_id": f"fictional-quarter-{index}",
                "revenue": str(100 + index * 10),
                "pat": str(10 + index),
                "ebitda": str(20 + index),
            }
        )
        await ingest_record(db, "results", data, "fixture-exchange", "NSE", None)
    for year in range(2022, 2027):
        data = Financial.model_validate(
            {
                **common,
                "financial_year": year,
                "period_type": "ANNUAL",
                "statement_type": "CONSOLIDATED",
                "period_start": f"{year-1}-04-01",
                "period_end": f"{year}-03-31",
                "filing_id": f"fictional-annual-{year}",
                "revenue": "400",
                "pat": "40",
            }
        )
        await ingest_record(db, "results", data, "fixture-exchange", "NSE", None)
    await ingest_record(
        db,
        "prices",
        Eod.model_validate(
            {**common, "price_date": "2026-07-20", "close": "145", "high": "150", "low": "140"}
        ),
        "fixture-eod",
        "LICENSED",
        None,
    )
    bank_data = Financial.model_validate(
        {
            **common,
            "isin": bank.isin,
            "financial_year": 2027,
            "quarter": 1,
            "period_type": "QUARTERLY",
            "statement_type": "STANDALONE",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "filing_id": "fictional-bank-result",
            "pat": "30",
            "industry_metrics": {
                "total_income": "300",
                "net_interest_income": "120",
                "gnpa": "2.5",
            },
        }
    )
    await ingest_record(db, "results", bank_data, "fixture-exchange", "NSE", None)
    # The existing open demo issue exercises the subscription/GMP public rendering.
    from sqlalchemy import select

    open_company = await db.scalar(
        select(m.Company)
        .join(m.IPO, m.IPO.company_id == m.Company.id)
        .where(m.IPO.status == "OPEN")
        .order_by(m.Company.slug)
    )
    open_company.isin = "INE000A04010"
    await db.flush()
    observed = {**common, "isin": open_company.isin}
    await ingest_record(
        db,
        "subscriptions",
        Subscriptions.model_validate(
            {
                **observed,
                "categories": {"retail": {"multiple": "2.5"}, "total": {"multiple": "3.75"}},
            }
        ),
        "fixture-exchange",
        "NSE",
        None,
    )
    await ingest_record(
        db,
        "gmp",
        Premium.model_validate({**observed, "value": "12"}),
        "fixture-unofficial",
        "UNOFFICIAL",
        None,
    )
    await db.commit()
