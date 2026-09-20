"""Strict XBRL instance parser for explicitly configured, reviewed taxonomy concepts.

Never guesses an EBITDA or industry-specific concept by substring. Feed adapters
must supply a discrete reporting context; segment/YTD contexts are rejected.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

from packages.providers.market import FeedError

NS = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}


def parse_instance(xml: str, context_id: str, concepts: dict[str, str], statement: str):
    if len(xml.encode()) > 2_000_000 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise FeedError("UNSAFE_XBRL")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FeedError("INVALID_XBRL") from exc
    contexts = [c for c in root.findall("x:context", NS) if c.get("id") == context_id]
    if len(contexts) != 1:
        raise FeedError("AMBIGUOUS_XBRL_CONTEXT")
    context = contexts[0]
    members = context.findall(".//d:explicitMember", NS)
    if context.findall(".//d:typedMember", NS) or len(members) > 1:
        raise FeedError("SEGMENT_CONTEXT_UNSUPPORTED")
    if members:
        label = (members[0].text or "").split(":")[-1].lower()
        expected = "consolidated" if statement == "CONSOLIDATED" else "standalone"
        if expected not in label:
            raise FeedError("STATEMENT_CONTEXT_MISMATCH")
    elif statement == "CONSOLIDATED":
        raise FeedError("CONSOLIDATION_CONTEXT_REQUIRED")
    start = context.findtext("x:period/x:startDate", namespaces=NS)
    end = context.findtext("x:period/x:endDate", namespaces=NS)
    if not start or not end:
        raise FeedError("DURATION_CONTEXT_REQUIRED")
    units = {u.get("id"): u for u in root.findall("x:unit", NS)}
    metrics = {}
    for key, concept in concepts.items():
        # Expanded XML QName includes the taxonomy namespace/version.
        facts = [f for f in root.findall(concept) if f.get("contextRef") == context_id]
        if not facts:
            metrics[key] = None
            continue
        if len(facts) != 1:
            raise FeedError("DUPLICATE_XBRL_FACT")
        fact = facts[0]
        if fact.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in ("true", "1"):
            metrics[key] = None
            continue
        unit = units.get(fact.get("unitRef"))
        if unit is None:
            raise FeedError("XBRL_UNIT_MISSING")
        measures = [e.text or "" for e in unit.findall(".//x:measure", NS)]
        if key in ("gnpa", "nnpa", "roe", "roce"):
            raise FeedError("RATIO_SCALE_REQUIRES_REVIEW")
        if not any(value.split(":")[-1] == "INR" for value in measures):
            raise FeedError("XBRL_CURRENCY_UNSUPPORTED")
        if (key == "eps") != (unit.find("x:divide", NS) is not None):
            raise FeedError("XBRL_UNIT_MISMATCH")
        if key == "eps" and (len(measures) != 2 or measures[-1].split(":")[-1] != "shares"):
            raise FeedError("XBRL_EPS_UNIT_MISMATCH")
        try:
            value = Decimal(fact.text or "")
            if not value.is_finite():
                raise ValueError()
            metrics[key] = value if key == "eps" else value / Decimal(10000000)
        except Exception as exc:
            raise FeedError("INVALID_XBRL_NUMBER") from exc
    if not any(value is not None for value in metrics.values()):
        raise FeedError("NO_MAPPED_XBRL_FACTS")
    return {"period_start": start, "period_end": end, "metrics": metrics}
