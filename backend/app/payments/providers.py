"""Payment providers.

- test:   simulated checkout inside the app (no money moves) - to try the flow.
- stripe: Stripe Checkout Session on the connected account of the tenant (Stripe Connect,
          header Stripe-Account). The platform key and the webhook secret come from .env.
          The webhook (POST /api/payments/stripe/webhook) is verified with the Stripe signature
          scheme: HMAC-SHA256 over "<timestamp>.<body>" with the webhook secret.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_config
from app.core.errors import AppError


@dataclass
class Checkout:
    provider_ref: str
    url: str
    raw: dict[str, Any]


class SimulatedProvider:
    name = "test"

    def create_checkout(
        self,
        payment_id: str,
        amount_eur: float,
        description: str,
        success_url: str,
        cancel_url: str,
        account: str | None,
    ) -> Checkout:
        return Checkout(
            provider_ref=f"test_{payment_id}", url=f"/kunde/zahlung/{payment_id}", raw={"simulated": True}
        )


class StripeProvider:
    name = "stripe"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def create_checkout(
        self,
        payment_id: str,
        amount_eur: float,
        description: str,
        success_url: str,
        cancel_url: str,
        account: str | None,
    ) -> Checkout:
        cfg = get_config()
        if not cfg.stripe_secret_key or not account:
            raise AppError("errors.payment_not_configured")
        data = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": payment_id,
            "metadata[payment_id]": payment_id,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "eur",
            "line_items[0][price_data][unit_amount]": str(int(round(amount_eur * 100))),
            "line_items[0][price_data][product_data][name]": description[:200] or "Zahlung",
        }
        with httpx.Client(base_url=cfg.stripe_api_base, transport=self.transport, timeout=20) as client:
            r = client.post(
                "/v1/checkout/sessions",
                data=data,
                auth=(cfg.stripe_secret_key, ""),
                headers={"Stripe-Account": account, "Idempotency-Key": f"kp-{payment_id}"},
            )
        if r.status_code >= 400:
            raise AppError("errors.payment_failed", detail=r.text[:200])
        body = r.json()
        return Checkout(provider_ref=body["id"], url=body["url"], raw={"id": body["id"]})


def provider_for(name: str):
    if name == "test":
        return SimulatedProvider()
    if name == "stripe":
        return StripeProvider()
    raise AppError("errors.payment_not_configured")


def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance_s: int = 300) -> bool:
    """Stripe-Signature: t=<timestamp>,v1=<hex hmac>[,v1=…]"""
    if not secret or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", "0"))
    except ValueError:
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    signatures = [v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p) if k == "v1"]
    return any(hmac.compare_digest(expected, s) for s in signatures)
