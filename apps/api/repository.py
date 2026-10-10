from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select

from packages.database import models as m
from packages.shared.calculations import (
    business_trend,
    data_quality,
    financial_quarter,
    financial_year,
    margin,
    percent_change,
    utc,
    valuation_label,
)
from packages.shared.config import settings
from packages.shared.ipo_lifecycle import lifecycle, public_status
from packages.shared.screener import screener_url

METRICS = ("revenue", "ebitda", "pat", "eps", "debt", "cfo", "roe", "roce")


def numeric(value):
    return float(value) if value is not None else None


def subscription_view(row):
    if not row:
        return None
    return {
        key: record(row)[key]
        for key in ("observed_at", "categories", "multiple", "source_provider", "source_url")
    }


def explain_subscription_gaps(result):
    """Expose missing denominators without inventing a category allocation."""
    categories = {key: dict(value) for key, value in (result.get("categories") or {}).items()}
    for key in ("retail", "qib", "nii", "total"):
        category = categories.setdefault(key, {"multiple": None})
        if category.get("multiple") is None:
            category["gap_note"] = (
                "Verified offered shares for this category are unavailable or reported as zero. "
                "No percentage is calculated; the whole IPO share count is not used as a substitute."
                if key != "total"
                else "The source does not provide a usable total offered-share count for this snapshot. "
                "The total percentage cannot be verified."
            )
    result["categories"] = categories
    return result


def merge_subscriptions(rows):
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    if not rows:
        return None
    consolidated = [r for r in rows if r.source_provider == "NSE_CONSOLIDATED"]
    if consolidated:
        # All-exchange counts are a coherent snapshot, not additive to exchange-only figures.
        row = max(consolidated, key=lambda r: utc(r.observed_at))
        result = subscription_view(row)
        result["categories"] = {
            key: {
                **value,
                "source_provider": row.source_provider,
                "source_url": row.source_url,
                "observed_at": utc(row.observed_at).isoformat(),
            }
            for key, value in row.categories.items()
        }
        result["source_disagreement"] = False
        return explain_subscription_gaps(result)
    rows = sorted(rows, key=lambda r: utc(r.observed_at), reverse=True)
    day = utc(rows[0].observed_at).astimezone(ZoneInfo("Asia/Kolkata")).date()
    rows = [
        r for r in rows if utc(r.observed_at).astimezone(ZoneInfo("Asia/Kolkata")).date() == day
    ]
    combined = subscription_view(rows[0])
    categories = {}
    for key in ("total", "retail", "qib", "nii", "bnii", "snii", "employee", "shareholder"):
        candidates = [r for r in rows if key in (r.categories or {})]
        preferred = "NSE" if key == "total" else "BSE"
        candidates.sort(
            key=lambda r: 0 if (r.source_exchange or r.source_provider) == preferred else 1
        )
        if candidates:
            row = candidates[0]
            categories[key] = {
                **row.categories[key],
                "source_provider": row.source_provider,
                "source_url": row.source_url,
                "observed_at": utc(row.observed_at).isoformat(),
            }
    combined["categories"] = categories
    combined["multiple"] = numeric(
        categories.get("total", {}).get("multiple", combined["multiple"])
    )
    totals = [
        Decimal(r.categories["total"]["multiple"])
        for r in rows
        if (r.categories or {}).get("total", {}).get("multiple") is not None
    ]
    combined["source_disagreement"] = len(totals) > 1 and max(totals) - min(totals) > Decimal(
        "0.01"
    )
    combined["source_provider"] = " / ".join(
        dict.fromkeys(r.source_provider or "Manual" for r in rows)
    )
    return explain_subscription_gaps(combined)


def metrics(obj):
    return (
        {key: numeric(getattr(obj, key)) for key in METRICS}
        if obj
        else {key: None for key in METRICS}
    )


def record(obj):
    from datetime import datetime
    from decimal import Decimal

    return {
        column.name: (
            utc(value).isoformat()
            if isinstance(value, datetime)
            else (
                value.isoformat()
                if isinstance(value, date)
                else float(value) if isinstance(value, Decimal) else value
            )
        )
        for column in obj.__table__.columns
        if column.name != "image_data"
        for value in [getattr(obj, column.name)]
    }


async def catalog(db, today=None):
    from packages.providers.bhavcopy import sources
    from packages.shared.market_config import load_market_settings

    closing_sources = sources((await load_market_settings(db)).bhavcopy_sources_json)
    today = today or m.now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    query = (
        select(m.Company, m.Sector, m.IPO, m.IPODate, m.PriceSnapshot, m.ApplicantGuide)
        .join(m.IPO, m.IPO.company_id == m.Company.id)
        .outerjoin(m.Sector, m.Sector.id == m.Company.sector_id)
        .outerjoin(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
        .outerjoin(m.PriceSnapshot, m.PriceSnapshot.company_id == m.Company.id)
        .outerjoin(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
        .order_by(m.IPODate.listing_date.desc(), m.Company.name)
    )
    if not settings().demo_mode:
        query = query.where(m.Company.is_demo.is_(False))
    rows = (await db.execute(query)).all()
    ids = [c.id for c, *_ in rows]
    ipo_ids = [ipo.id for _, _, ipo, *_ in rows]
    if not ids:
        return []
    quarter_rows = (
        await db.execute(
            select(m.Quarterly, m.Period)
            .join(m.Period)
            .where(m.Quarterly.company_id.in_(ids))
            .order_by(m.Period.financial_year, m.Period.quarter, m.Quarterly.revision)
        )
    ).all()
    quarters = {}
    for q, period in quarter_rows:
        existing = quarters.get(q.company_id, {}).get((period.financial_year, period.quarter))
        if (
            existing
            and existing.get("statement_type") == "CONSOLIDATED"
            and q.statement_type != "CONSOLIDATED"
        ):
            continue
        quarters.setdefault(q.company_id, {})[(period.financial_year, period.quarter)] = {
            **metrics(q),
            **{k: numeric(v) for k, v in (q.industry_metrics or {}).items()},
            "statement_type": q.statement_type,
            "source_provider": q.source_provider,
            "source_timestamp": utc(q.source_timestamp).isoformat() if q.source_timestamp else None,
            "fetched_at": utc(q.created_at).isoformat(),
            "financial_year": period.financial_year,
            "quarter": period.quarter,
            "label": f"Q{period.quarter} FY{str(period.financial_year)[-2:]}",
            "source_url": q.source_url,
            "verification_status": q.verification_status,
            "revision": q.revision,
        }
    # The tracker reads the same canonical validated results as Company Details.
    # Monetary facts are INR in storage; the existing tracker contract is crore.
    normalized = (
        await db.execute(
            select(m.FinancialResult, m.ResultFiling)
            .join(m.ResultFiling, m.ResultFiling.id == m.FinancialResult.filing_id)
            .where(
                m.FinancialResult.company_id.in_(ids),
                m.FinancialResult.current.is_(True),
                m.FinancialResult.period_type == "QUARTERLY",
            )
            .order_by(m.FinancialResult.period_end)
        )
    ).all()
    preferred = {}
    for result_row, _ in normalized:
        if result_row.basis == "CONSOLIDATED" or result_row.company_id not in preferred:
            preferred[result_row.company_id] = result_row.basis
    for result_row, filing in normalized:
        if result_row.basis != preferred[result_row.company_id]:
            continue
        fy, quarter = financial_year(result_row.period_end), financial_quarter(
            result_row.period_end
        )
        values = {key: None for key in METRICS}
        for key in ("revenue", "pat", "total_income"):
            value = result_row.facts.get(key)
            values[key] = numeric(Decimal(value) / Decimal(10000000)) if value is not None else None
        values["eps"] = numeric(result_row.facts.get("basic_eps"))
        quarters.setdefault(result_row.company_id, {})[(fy, quarter)] = {
            **values,
            "statement_type": result_row.basis,
            "source_provider": filing.exchange,
            "source_timestamp": utc(filing.announced_at).isoformat(),
            "fetched_at": utc(result_row.updated_at).isoformat(),
            "financial_year": fy,
            "quarter": quarter,
            "label": f"Q{quarter} FY{str(fy)[-2:]}",
            "source_url": (
                filing.metadata_json.get("attachments") or [filing.metadata_json["source_url"]]
            )[0],
            "verification_status": "VERIFIED",
            "revision": result_row.revision,
        }
    for company_id, basis in preferred.items():
        quarters[company_id] = {
            key: value
            for key, value in quarters[company_id].items()
            if value.get("statement_type") == basis
        }
    gmp_rows = (
        await db.scalars(select(m.GMP).where(m.GMP.ipo_id.in_(ipo_ids)).order_by(m.GMP.observed_at))
    ).all()
    gmps = {g.ipo_id: g for g in gmp_rows}
    ranked = (
        select(
            m.Subscription.id,
            func.row_number()
            .over(
                partition_by=(m.Subscription.ipo_id, m.Subscription.source_provider),
                order_by=(m.Subscription.observed_at.desc(), m.Subscription.created_at.desc()),
            )
            .label("rn"),
        )
        .where(m.Subscription.ipo_id.in_(ipo_ids))
        .subquery()
    )
    subscriptions = {}
    for s in (
        await db.scalars(
            select(m.Subscription)
            .join(ranked, ranked.c.id == m.Subscription.id)
            .where(ranked.c.rn == 1)
        )
    ).all():
        subscriptions.setdefault(s.ipo_id, []).append(s)
    provider_details = {
        detail.ipo_id: detail
        for detail in (
            await db.scalars(
                select(m.IPOProviderDetail).where(m.IPOProviderDetail.ipo_id.in_(ipo_ids))
            )
        ).all()
    }
    identifiers = {
        i.company_id: i
        for i in (
            await db.scalars(
                select(m.Identifier)
                .where(
                    m.Identifier.company_id.in_(ids),
                    m.Identifier.exchange.in_(["NSE", "BSE", "BSE_SYMBOL", "BSE_ISSUE"]),
                )
                .order_by(
                    case(
                        (m.Identifier.exchange == "NSE", 3),
                        (m.Identifier.exchange == "BSE", 2),
                        (m.Identifier.exchange == "BSE_SYMBOL", 1),
                        else_=0,
                    ),
                    m.Identifier.ticker,
                )
            )
        ).all()
    }
    screener_identifiers = {}
    for identity in (
        await db.scalars(
            select(m.Identifier).where(
                m.Identifier.company_id.in_(ids), m.Identifier.exchange.in_(["BSE", "NSE"])
            )
        )
    ).all():
        screener_identifiers.setdefault(identity.company_id, []).append(
            (identity.exchange, identity.ticker)
        )
    values = {
        v.company_id: v
        for v in (
            await db.scalars(
                select(m.Valuation)
                .where(m.Valuation.company_id.in_(ids))
                .order_by(m.Valuation.as_of)
            )
        ).all()
    }
    conflicts = {
        q.company_id
        for q in (
            await db.scalars(
                select(m.QualityIssue).where(
                    m.QualityIssue.company_id.in_(ids),
                    m.QualityIssue.kind == "CONFLICT",
                    m.QualityIssue.resolved.is_(False),
                )
            )
        ).all()
    }
    result = []
    for company, sector, ipo, dates, price, guide in rows:
        closing_exchange = price.closing_exchange if price else None
        if closing_exchange and not closing_sources[closing_exchange].public_display_allowed:
            price = None
        periods = quarters.get(company.id, {})
        history = [periods[key] for key in sorted(periods)]
        for q in history:
            prior = periods.get((q["financial_year"] - 1, q["quarter"]), {})
            previous = periods.get(
                (
                    q["financial_year"] - (q["quarter"] == 1),
                    4 if q["quarter"] == 1 else q["quarter"] - 1,
                ),
                {},
            )
            if prior.get("statement_type") != q.get("statement_type"):
                prior = {}
            if previous.get("statement_type") != q.get("statement_type"):
                previous = {}
            for key in (
                "revenue",
                "pat",
                "ebitda",
                "total_income",
                "net_interest_income",
                "operating_profit",
            ):
                q[key + "_qoq"] = numeric(percent_change(q.get(key), previous.get(key)))
                q[key + "_yoy"] = numeric(percent_change(q.get(key), prior.get(key)))
            q["revenue_yoy"] = numeric(percent_change(q["revenue"], prior.get("revenue")))
            q["pat_yoy"] = numeric(percent_change(q["pat"], prior.get("pat")))
            q["ebitda_yoy"] = numeric(percent_change(q["ebitda"], prior.get("ebitda")))
            q["margin"] = numeric(margin(q["ebitda"], q["revenue"]))
            for label, comparison in (("qoq", previous), ("yoy", prior)):
                old_margin = margin(comparison.get("ebitda"), comparison.get("revenue"))
                q["margin_" + label + "_bps"] = (
                    round((q["margin"] - float(old_margin)) * 100, 2)
                    if q["margin"] is not None and old_margin is not None
                    else None
                )
        latest = history[-1] if history else {}
        trend = business_trend(latest, history[-2] if len(history) > 1 else {})
        gmp, identifier, valuation = (
            gmps.get(ipo.id),
            identifiers.get(company.id),
            values.get(company.id),
        )
        cmp = numeric(price.cmp) if price else None
        drawdown = numeric(percent_change(cmp, price.ath if price else None))
        listing = dates.listing_date if dates else None
        listing_price = None
        if (
            company.listing_price_date == listing
            and company.listing_price_exchange
            and closing_sources[company.listing_price_exchange].public_display_allowed
        ):
            listing_price = company.listing_price
        elif company.is_demo:
            listing_price = ipo.listing_price
        current_lifecycle = (
            lifecycle(ipo, dates, guide, today)
            if ipo.source_provider
            else (ipo.lifecycle or ipo.status)
        )
        current_status = public_status(current_lifecycle)
        quality = data_quality(
            conflict=company.id in conflicts,
            missing=not identifier or (current_status == "LISTED" and not latest),
            verified=ipo.quality == "VERIFIED",
        )
        result.append(
            {
                "id": company.id,
                "ipo_id": ipo.id,
                "slug": company.slug,
                "name": company.name,
                "company_type": company.company_type,
                "lifecycle": current_lifecycle,
                "sector": sector.name if sector else "Unclassified",
                "board": company.board,
                "is_demo": company.is_demo,
                "ticker": (
                    identifier.ticker if identifier and identifier.exchange != "BSE_ISSUE" else None
                ),
                "exchange": (
                    (
                        "BSE"
                        if identifier.exchange in {"BSE_SYMBOL", "BSE_ISSUE"}
                        else identifier.exchange
                    )
                    if identifier
                    else None
                ),
                "status": current_status,
                "quality": quality,
                "open_date": dates.open_date.isoformat() if dates and dates.open_date else None,
                "close_date": dates.close_date.isoformat() if dates and dates.close_date else None,
                "listing_date": listing.isoformat() if listing else None,
                "listing_fy": financial_year(listing) if listing else None,
                "listing_quarter": financial_quarter(listing) if listing else None,
                "price_low": numeric(ipo.price_low),
                "price_high": numeric(ipo.price_high),
                "issue_price": numeric(ipo.issue_price),
                "listing_price": numeric(listing_price),
                "listing_price_date": (
                    listing.isoformat() if listing_price is not None and listing else None
                ),
                "listing_price_exchange": (
                    company.listing_price_exchange if listing_price is not None else None
                ),
                "listing_gain": numeric(percent_change(listing_price, ipo.price_high)),
                "lot_size": ipo.lot_size,
                "applicant_guide": record(guide) if guide else None,
                "provider_details": (
                    {
                        **provider_details[ipo.id].data,
                        "provider": provider_details[ipo.id].provider,
                        "source_url": provider_details[ipo.id].source_url,
                        "fetched_at": provider_details[ipo.id].fetched_at.isoformat(),
                    }
                    if ipo.id in provider_details
                    else None
                ),
                "minimum_application": (
                    numeric(ipo.price_high * ipo.lot_size * guide.min_lots)
                    if ipo.price_high is not None
                    and ipo.lot_size is not None
                    and guide
                    and guide.min_lots
                    and (guide.verification_status == "VERIFIED" or company.is_demo)
                    else None
                ),
                "issue_size": numeric(ipo.issue_size),
                "fresh_issue": numeric(ipo.fresh_issue),
                "ofs": numeric(ipo.ofs),
                "gmp": numeric(gmp.value) if gmp else None,
                "subscription": merge_subscriptions(subscriptions.get(ipo.id, [])),
                "gmp_estimated_price": (
                    numeric(ipo.price_high + gmp.value)
                    if gmp and gmp.value is not None and ipo.price_high
                    else None
                ),
                "gmp_percent": (
                    numeric(gmp.value / ipo.price_high * 100)
                    if gmp and gmp.value is not None and ipo.price_high
                    else None
                ),
                "gmp_timestamp": gmp.observed_at.isoformat() if gmp else None,
                "gmp_quality": data_quality(
                    missing=not gmp or gmp.value is None,
                    observed_at=gmp.observed_at if gmp else None,
                    ttl_hours=settings().gmp_ttl_hours,
                ),
                "cmp": cmp,
                "price_date": price.price_date.isoformat() if price and price.price_date else None,
                "closing_exchange": closing_exchange if price else None,
                "daily_change_pct": (
                    numeric(percent_change(price.cmp, price.previous_close))
                    if price and price.previous_close
                    else None
                ),
                "ath": numeric(price.ath) if price else None,
                "high_52w": numeric(price.high_52w) if price else None,
                "low_52w": numeric(price.low_52w) if price else None,
                "return_ipo": numeric(percent_change(cmp, ipo.price_high)),
                "return_listing": numeric(percent_change(cmp, listing_price)),
                "drawdown": drawdown,
                "latest": latest,
                "quarters": history,
                "trend": trend,
                "business_vs_price": trend["state"].replace("_", " ").title()
                + (
                    " / Price corrected"
                    if drawdown is not None and drawdown <= -20
                    else (
                        " / Price up"
                        if cmp is not None and ipo.price_high is not None and cmp >= ipo.price_high
                        else " / Price down" if cmp is not None else " / Price pending"
                    )
                ),
                "valuation": record(valuation) if valuation else None,
                "valuation_label": (
                    valuation_label(valuation.pe, valuation.peer_median_pe)
                    if valuation
                    else "Data unavailable"
                ),
                "screener_url": screener_url(
                    company.screener_url, screener_identifiers.get(company.id, [])
                ),
                "exchange_url": company.exchange_url,
            }
        )
    return result


async def journey(db, slug):
    company = next((c for c in await catalog(db) if c["slug"] == slug), None)
    if not company:
        return None
    annual_rows = (
        await db.scalars(
            select(m.Annual)
            .where(m.Annual.company_id == company["id"])
            .order_by(m.Annual.financial_year.desc(), m.Annual.revision.desc())
        )
    ).all()
    annual = {}
    for row in annual_rows:
        existing = annual.get(row.financial_year)
        if existing and (
            existing.statement_type == "CONSOLIDATED" or row.statement_type != "CONSOLIDATED"
        ):
            continue
        annual[row.financial_year] = row
    company["annuals"] = [
        {**record(row), **{k: numeric(v) for k, v in (row.industry_metrics or {}).items()}}
        for row in list(annual.values())[:4]
    ]
    history = (
        await db.execute(
            select(m.SubscriptionDay, m.SubscriptionDetail)
            .join(m.SubscriptionDetail, m.SubscriptionDetail.day_id == m.SubscriptionDay.id)
            .where(m.SubscriptionDay.company_id == company["id"])
            .order_by(
                m.SubscriptionDay.subscription_date.desc(),
                m.SubscriptionDay.exchange,
                m.SubscriptionDetail.category,
            )
            .limit(240)
        )
    ).all()
    company["subscription_history"] = [
        {
            "date": day.subscription_date.isoformat(),
            "exchange": day.exchange,
            "category": detail.category,
            "multiple": numeric(detail.multiple),
            "subscription_pct": (
                numeric(detail.multiple * 100) if detail.multiple is not None else None
            ),
            "bid_shares": numeric(detail.bid_shares),
            "offered_shares": numeric(detail.offered_shares),
        }
        for day, detail in history
    ]
    baseline = await db.scalar(select(m.Baseline).where(m.Baseline.ipo_id == company["ipo_id"]))
    company["baseline"] = {
        **metrics(baseline),
        "margin": numeric(margin(baseline.ebitda, baseline.revenue)) if baseline else None,
        "pe": numeric(baseline.pe) if baseline else None,
        "market_cap": numeric(baseline.market_cap) if baseline else None,
    }
    company["documents"] = [
        record(d)
        for d in (
            await db.scalars(select(m.Document).where(m.Document.ipo_id == company["ipo_id"]))
        ).all()
    ]
    company["prices"] = [
        record(p)
        for p in (
            await db.scalars(
                select(m.Price)
                .where(m.Price.company_id == company["id"])
                .order_by(m.Price.price_date)
            )
        ).all()
    ]
    closing_snapshot = await db.scalar(
        select(m.PriceSnapshot).where(m.PriceSnapshot.company_id == company["id"])
    )
    if closing_snapshot and closing_snapshot.closing_exchange:
        # New bhavcopy histories are always one exchange; do not combine legacy or intraday data.
        company["prices"] = (
            [
                {**record(p), "price_date": p.trade_date.isoformat()}
                for p in (
                    await db.scalars(
                        select(m.DailyClose)
                        .where(
                            m.DailyClose.company_id == company["id"],
                            m.DailyClose.exchange == company["closing_exchange"],
                        )
                        .order_by(m.DailyClose.trade_date)
                    )
                ).all()
            ]
            if company.get("closing_exchange")
            else []
        )
        company["prices_adjusted"] = False
    company["sources"] = [
        record(p)
        for p in (
            await db.scalars(
                select(m.Provenance)
                .where(
                    m.Provenance.entity_id.in_(
                        [
                            company["id"],
                            company["ipo_id"],
                            (company.get("applicant_guide") or {}).get("id", ""),
                        ]
                    )
                )
                .order_by(m.Provenance.fetched_at.desc())
                .limit(100)
            )
        ).all()
    ]
    company["gmp_history"] = [
        record(g)
        for g in (
            await db.scalars(
                select(m.GMP)
                .where(m.GMP.ipo_id == company["ipo_id"])
                .order_by(m.GMP.observed_at.desc())
                .limit(50)
            )
        ).all()
    ]
    company["performance"] = {}
    if company["prices"]:
        latest_date = date.fromisoformat(company["prices"][-1]["price_date"])
        for label, days in (("1M", 30), ("3M", 90), ("6M", 180), ("1Y", 365)):
            earlier = [
                p
                for p in company["prices"]
                if date.fromisoformat(p["price_date"]) <= latest_date - timedelta(days=days)
            ]
            company["performance"][label] = (
                numeric(percent_change(company["cmp"], earlier[-1]["close"])) if earlier else None
            )
    from apps.worker.results import public_results

    company["financial_performance"] = await public_results(db, company["id"])
    return company
