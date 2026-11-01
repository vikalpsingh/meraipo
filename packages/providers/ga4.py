"""Optional GA4 Data API reports. Credentials never enter browser responses."""

import asyncio
import base64
import json
import re
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from apps.api.cache import client as cache
from packages.shared.config import settings


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


async def reports(start, end):
    config = settings()
    if not config.ga4_property_id or not config.ga4_service_account_file:
        return {
            "status": "NOT_CONNECTED",
            "message": "GA4 is not connected. Clicks are not website sessions.",
        }
    if not re.fullmatch(r"\d+", config.ga4_property_id):
        return {"status": "UNAVAILABLE", "message": "Invalid GA4 property configuration."}
    key = f"email-ga4:{config.ga4_property_id}:{start}:{end}"
    try:
        saved = await cache.get(key)
        if saved:
            return json.loads(saved)
    except Exception:
        pass
    try:
        raw = Path(config.ga4_service_account_file).read_bytes()
        if len(raw) > 64000:
            raise ValueError()
        credentials = json.loads(raw)
        current = int(time.time())
        head = encoded(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = encoded(
            json.dumps(
                {
                    "iss": credentials["client_email"],
                    "scope": "https://www.googleapis.com/auth/analytics.readonly",
                    "aud": "https://oauth2.googleapis.com/token",
                    "iat": current,
                    "exp": current + 3600,
                }
            ).encode()
        )
        signing = f"{head}.{claims}".encode()
        private = serialization.load_pem_private_key(
            credentials["private_key"].encode(), password=None
        )
        assertion = (
            signing.decode()
            + "."
            + encoded(private.sign(signing, padding.PKCS1v15(), hashes.SHA256()))
        )
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            response.raise_for_status()
            bearer = response.json()["access_token"]

            async def report(dimensions, metrics):
                body = {
                    "dateRanges": [{"startDate": str(start), "endDate": str(end)}],
                    "dimensions": [{"name": d} for d in dimensions],
                    "metrics": [{"name": m} for m in metrics],
                    "dimensionFilter": {
                        "andGroup": {
                            "expressions": [
                                {
                                    "filter": {
                                        "fieldName": "sessionSourceMedium",
                                        "stringFilter": {
                                            "matchType": "EXACT",
                                            "value": "meraipo_email / email",
                                        },
                                    }
                                },
                                {
                                    "filter": {
                                        "fieldName": "sessionCampaignName",
                                        "stringFilter": {
                                            "matchType": "FULL_REGEXP",
                                            "value": "ipo_(prelisting|opening)",
                                        },
                                    }
                                },
                            ]
                        }
                    },
                    "limit": "100000",
                }
                r = await http.post(
                    f"https://analyticsdata.googleapis.com/v1beta/properties/{config.ga4_property_id}:runReport",
                    json=body,
                    headers={"Authorization": "Bearer " + bearer},
                )
                r.raise_for_status()
                result = r.json()
                metadata = result.get("metadata", {})
                if (
                    metadata.get("subjectToThresholding")
                    or metadata.get("samplingMetadatas")
                    or metadata.get("dataLossFromOtherRow")
                ):
                    raise ValueError("Report is sampled or thresholded")
                if result.get("rowCount", 0) > 100000:
                    raise ValueError("Truncated report")
                if result.get("metadata", {}).get("timeZone") not in (
                    "Asia/Kolkata",
                    "Asia/Calcutta",
                ):
                    raise ValueError("GA4 property timezone must be IST")
                return [
                    {
                        "dimensions": [v["value"] for v in row.get("dimensionValues", [])],
                        **{
                            name: float(value["value"])
                            for name, value in zip(metrics, row["metricValues"], strict=True)
                        },
                    }
                    for row in result.get("rows", [])
                ]

            metrics = ["sessions", "engagedSessions", "userEngagementDuration"]
            total, daily, campaigns, landing_pages = await asyncio.gather(
                report([], metrics),
                report(["date"], metrics),
                report(["sessionManualAdContent"], metrics),
                report(["landingPage"], metrics),
            )
            # Separate report avoids incompatible user/session metric combinations.
            try:
                returning = await report(["newVsReturning"], ["totalUsers"])
                returning_users = sum(
                    r["totalUsers"] for r in returning if r["dimensions"] == ["returning"]
                )
            except (ValueError, KeyError, httpx.HTTPError):
                returning_users = None
            data = {
                "status": "CONNECTED",
                "message": "GA4 consented traffic; reporting may be delayed. Returning users are GA4 returning users, not a longitudinal email cohort.",
                "fetched_at": current,
                "totals": total[0] if total else dict.fromkeys(metrics, 0),
                "returning_users": returning_users,
                "daily": daily,
                "campaigns": campaigns,
                "landing_pages": [
                    r for r in landing_pages if re.fullmatch(r"/ipo/[a-z0-9-]+", r["dimensions"][0])
                ],
            }
        try:
            await cache.setex(key, 3600, json.dumps(data))
        except Exception:
            pass
        return data
    except Exception:
        return {
            "status": "UNAVAILABLE",
            "message": "GA4 report unavailable or incompatible. Check credentials, property access and IST timezone; reporting may be delayed.",
        }
