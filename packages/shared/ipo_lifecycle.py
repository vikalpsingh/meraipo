"""Shared date rules for scheduled persistence and current public views."""


def lifecycle(ipo, dates, guide, today):
    if ipo.raw_status in ("WITHDRAWN", "CANCELLED"):
        return ipo.raw_status
    if dates and dates.listing_date and today >= dates.listing_date:
        return "LISTING_TODAY" if today == dates.listing_date else "LISTED"
    if ipo.raw_status == "LISTED":
        return "LISTED"
    if dates and dates.open_date and today < dates.open_date:
        return "UPCOMING"
    if (
        dates
        and dates.open_date
        and dates.close_date
        and dates.open_date <= today <= dates.close_date
    ):
        return "OPEN"
    if dates and dates.close_date and today > dates.close_date:
        if dates.allotment_date:
            return "ALLOTMENT_COMPLETED" if today >= dates.allotment_date else "ALLOTMENT_PENDING"
        if guide and guide.schedule_status == "CONFIRMED" and guide.allotment_date:
            return "ALLOTMENT_COMPLETED" if today >= guide.allotment_date else "ALLOTMENT_PENDING"
        return "CLOSED"
    return (
        ipo.raw_status
        if ipo.raw_status
        in ("LISTED", "OPEN", "UPCOMING", "CLOSED", "ALLOTMENT_PENDING", "ALLOTMENT_COMPLETED")
        else "ANNOUNCED"
    )


def public_status(state):
    return {
        "LISTING_TODAY": "LISTED",
        "ANNOUNCED": "UPCOMING",
        "ALLOTMENT_PENDING": "CLOSED",
        "ALLOTMENT_COMPLETED": "CLOSED",
        "WITHDRAWN": "CLOSED",
        "CANCELLED": "CLOSED",
    }.get(state, state)
