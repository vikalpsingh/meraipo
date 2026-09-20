from datetime import date, timedelta

import pytest
from sqlalchemy import select

from packages.database.models import Audit, Company


def payload(**values):
    return {
        "category": "Retail individual",
        "min_lots": 1,
        "max_amount": 200000,
        "source_url": "https://example.com/rhp",
        "reviewed_on": date.today().isoformat(),
        "verification_status": "VERIFIED",
        "business_summary": "Makes industrial components.",
        **values,
    }


async def test_guide_requires_session_and_csrf(client, admin_client):
    path = "/api/v1/admin/ipos/aarya-energy/applicant-guide"
    assert (
        await admin_client.put(path, json=payload(), headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    await admin_client.post("/api/v1/admin/logout", json={})
    assert (await client.put(path, json=payload())).status_code == 401


async def test_guide_edit_preserves_financials_and_records_audit(admin_client, db):
    path = "/api/v1/admin/ipos/aarya-energy/applicant-guide"
    data = payload(
        registrar_name="Example registrar",
        registrar_url="https://example.com/allotment",
        strengths="Recurring demand\nCapacity expansion",
        risks="Customer concentration",
    )
    response = await admin_client.put(path, json=data)
    assert response.status_code == 200, response.text
    result = (await admin_client.get("/api/v1/companies/aarya-energy")).json()
    assert result["price_high"] == 150
    assert result["minimum_application"] == 7500
    assert result["applicant_guide"]["registrar_name"] == "Example registrar"
    assert any(s["field_name"] == "registrar_url" for s in result["sources"])
    assert (
        await db.scalar(select(Audit).where(Audit.action == "applicant_guide_updated"))
    ) is not None
    company = await db.scalar(select(Company).where(Company.slug == "aarya-energy"))
    company.is_demo = False
    await db.commit()
    await admin_client.put(path, json={**data, "verification_status": "UNVERIFIED"})
    assert (await admin_client.get("/api/v1/companies/aarya-energy")).json()[
        "minimum_application"
    ] is None


@pytest.mark.parametrize(
    "change",
    [
        {"min_lots": 0},
        {"min_lots": 3, "max_lots": 2},
        {"max_amount": 1},
        {"registrar_name": "Missing URL"},
        {"registrar_name": "Unsafe", "registrar_url": "javascript:alert(1)"},
        {"bid_deadline": "2026-09-22T16:00:00"},
        {"reviewed_on": (date.today() + timedelta(days=1)).isoformat()},
        {"strengths": "one\ntwo\nthree\nfour"},
        {"allotment_date": "2000-01-01"},
    ],
)
async def test_invalid_guide_is_rejected(admin_client, change):
    response = await admin_client.put(
        "/api/v1/admin/ipos/aarya-energy/applicant-guide", json=payload(**change)
    )
    assert response.status_code == 422, response.text


async def test_sme_does_not_guess_one_lot_or_publish_unreviewed_amount(client):
    c = (await client.get("/api/v1/companies/cedar-foods")).json()
    assert c["board"] == "SME" and c["minimum_application"] is None
