"""SNS signature verification: trusted topic and certificate host, no arbitrary fetches."""

import base64
import json
import re
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from packages.database.models import now
from packages.shared.config import settings


async def verify_sns(body):
    topic = settings().ses_sns_topic_arn
    if (
        not re.fullmatch(r"arn:aws:sns:[a-z0-9-]+:\d{12}:[A-Za-z0-9_-]+", topic)
        or body.get("TopicArn") != topic
    ):
        raise HTTPException(403, "Untrusted notification topic")
    region = topic.split(":")[3]
    cert_url = body.get("SigningCertURL", "")
    parts = urlsplit(cert_url)
    if (
        parts.scheme != "https"
        or parts.netloc != f"sns.{region}.amazonaws.com"
        or parts.query
        or parts.fragment
        or not re.fullmatch(r"/SimpleNotificationService-[A-Za-z0-9]+\.pem", parts.path)
    ):
        raise HTTPException(403, "Untrusted signing certificate")
    kind = body.get("Type")
    if kind == "Notification":
        fields = (
            ["Message", "MessageId"]
            + (["Subject"] if "Subject" in body else [])
            + ["Timestamp", "TopicArn", "Type"]
        )
    elif kind == "SubscriptionConfirmation":
        fields = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        raise HTTPException(400, "Unsupported notification")
    try:
        from datetime import datetime

        stamp = datetime.fromisoformat(body["Timestamp"].replace("Z", "+00:00"))
        if not stamp.tzinfo or not now() - timedelta(hours=24) <= stamp <= now() + timedelta(
            minutes=5
        ):
            raise ValueError()
        canonical = "".join(f"{key}\n{body[key]}\n" for key in fields).encode()
        algorithm = {"1": hashes.SHA1, "2": hashes.SHA256}[body["SignatureVersion"]]()
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            async with client.stream("GET", cert_url) as response:
                response.raise_for_status()
                data = b""
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > 20000:
                        raise ValueError()
        cert = x509.load_pem_x509_certificate(data)
        if not cert.not_valid_before_utc <= now() <= cert.not_valid_after_utc:
            raise ValueError()
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            raise ValueError()
        key.verify(
            base64.b64decode(body["Signature"], validate=True),
            canonical,
            padding.PKCS1v15(),
            algorithm,
        )
    except Exception:
        raise HTTPException(403, "Notification signature verification failed") from None
    if kind == "SubscriptionConfirmation":
        # Confirm through the AWS API, never follow an untrusted SubscribeURL.
        import asyncio

        import boto3

        await asyncio.to_thread(
            boto3.client("sns", region_name=region).confirm_subscription,
            TopicArn=topic,
            Token=body["Token"],
            AuthenticateOnUnsubscribe="true",
        )
        return None
    try:
        message = json.loads(body["Message"])
        if not isinstance(message, dict):
            raise ValueError()
        return message
    except ValueError:
        raise HTTPException(400, "Invalid provider event") from None
