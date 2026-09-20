# Applicant experience

The public navigation remains Home, IPO Tracker and About/Methodology. The home page adds a compact, India-time action strip: closing today, opening next, allotment due and listing today. Additional issues in each group expand on demand.

An unlisted company's guide follows Understand → Prepare to apply → Track dates. It includes an editorial business brief, up to three strengths and risks, use of proceeds, a category-aware application calculator, an optional personal checklist, a timeline, calendar export and a reviewed registrar link. Listed companies retain financial history as their primary view.

## Maintaining a guide

In `/meraadmin`, select **Applicant guides**, choose a company and enter:

- A named investor category, minimum lots and either maximum lots or a maximum application amount. Rules are per issue; they are not inferred from a payment-method limit. For an SME individual category, confirm the applicable issue's current two-lot requirement and amount in the prospectus/exchange notice rather than reusing Mainboard values.
- Actual bidding and UPI mandate deadlines, entered in IST; unknown times remain blank. Allotment and unblocking initiation dates, and tentative/published schedule status. Opening/closing/listing dates remain under IPO maintenance.
- The registrar's name and official allotment destination. Check the destination before marking verified. Public links are enabled only for verified, non-demo guides.
- A short plain-language business explanation, three sourced strengths/risks, and use of proceeds. Cite the original filing and enter the review date. The summary provides research context, not an apply/avoid rating.

Save is validated, audited and cache-invalidated. The API is `PUT /api/v1/admin/ipos/{slug}/applicant-guide`, with the same session/CSRF requirements as other admin writes. Guide records use a separate typed SQL table, so ordinary IPO edits do not silently overwrite editorial content. Source history includes guide provenance.

## Behaviour and limits

- The calculator uses the upper price band and the issue's lot size. It rejects fractions, zero, unsafe numeric ranges and amounts outside the configured category. It does not submit applications, select a broker or estimate allotment odds. Incomplete/unverified rules disable live calculations; demo calculations are visibly illustrative.
- The checklist is temporary, local React state for the current visit. No PAN, bank, UPI or demat details are collected. Checked items are self-reported, never presented as broker-confirmed status.
- Calendar downloads are RFC-style `.ics` files with stable event IDs, escaped/folded text and UTC timestamps for timed IST deadlines. Unknown dates are omitted. Tentative/unverified/demo schedules are labelled; reminders are included, but clients control how they are handled. Downloaded calendars do not update automatically.
- Registrar navigation opens the reviewed external site. Allotment may remain unpublished even on the expected date. No registrar scraping, login integration or personal identifier collection is included.
- Home summaries use India calendar dates; they do not infer operational bid acceptance from a closing date. The detailed page explains that broker cutoffs may be earlier.

## Migration and verification

Apply `python -m alembic upgrade head` to create `ipo_applicant_guides`. Existing real records have no guide until an administrator reviews one. Existing demo data is not overwritten by the idempotent seed. Clear the public cache or allow its TTL to expire during rollout.

Unit/component tests cover calculations, SME bounds, missing rules, IST date boundaries, calendar escaping, checklist state, registrar verification and action deduplication. API tests cover permissions, CSRF, source/audit history, financial-data preservation and invalid guide inputs. Playwright exercises admin publishing, the applicant flow and missing-data behaviour on desktop and mobile. The full production PostgreSQL/Redis release gate remains required.
