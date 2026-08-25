"""`python scripts/capture_golden.py` — Captures live Razorpay test-mode API payloads.

Writes real JSON responses to data/golden/ to ground the synthetic generator
and live executor schemas to production Razorpay API contracts.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.config import load_dotenv

GOLDEN_DIR = ROOT_DIR / "data" / "golden"


def capture_all() -> None:
    load_dotenv()
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        print("Error: RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env", file=sys.stderr)
        sys.exit(1)

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    auth = (key_id, key_secret)

    with httpx.Client(auth=auth, timeout=15.0) as client:
        # 1. Capture Order Creation (/v1/orders)
        order_receipt = f"rcpt_golden_{uuid.uuid4().hex[:8]}"
        order_payload = {
            "amount": 499900,
            "currency": "INR",
            "receipt": order_receipt,
            "notes": {"purpose": "golden_dataset_capture", "timestamp": datetime.now(timezone.utc).isoformat()},
        }
        resp_order = client.post("https://api.razorpay.com/v1/orders", json=order_payload)
        resp_order.raise_for_status()
        order_data = resp_order.json()
        (GOLDEN_DIR / "razorpay_order_created.json").write_text(json.dumps(order_data, indent=2), encoding="utf-8")
        print(f"Captured: {GOLDEN_DIR / 'razorpay_order_created.json'} (ID: {order_data.get('id')})")

        # 2. Capture Payment Link (/v1/payment_links)
        pl_ref = f"pl_ref_{uuid.uuid4().hex[:12]}"
        pl_payload = {
            "amount": 249900,
            "currency": "INR",
            "accept_partial": False,
            "description": "Golden Dataset Recovery Link Verification",
            "reference_id": pl_ref,
            "customer": {
                "name": "Arjun Mehta",
                "contact": "+919876543210",
                "email": "arjun.mehta@example.com",
            },
            "notify": {"sms": False, "email": False},
            "reminder_enable": True,
            "notes": {"purpose": "golden_dataset_capture", "order_id": order_data.get("id")},
        }
        resp_pl = client.post("https://api.razorpay.com/v1/payment_links", json=pl_payload)
        resp_pl.raise_for_status()
        pl_data = resp_pl.json()
        (GOLDEN_DIR / "razorpay_payment_link_created.json").write_text(json.dumps(pl_data, indent=2), encoding="utf-8")
        print(f"Captured: {GOLDEN_DIR / 'razorpay_payment_link_created.json'} (ID: {pl_data.get('id')})")

        # 3. Capture Payments List / Payment Schema Entity (/v1/payments)
        resp_payments = client.get("https://api.razorpay.com/v1/payments", params={"count": 5})
        resp_payments.raise_for_status()
        payments_data = resp_payments.json()
        (GOLDEN_DIR / "razorpay_payments_list.json").write_text(json.dumps(payments_data, indent=2), encoding="utf-8")
        print(f"Captured: {GOLDEN_DIR / 'razorpay_payments_list.json'}")

        # 4. Save Standard Golden Downtime Schema Contract
        downtime_fixture = {
            "entity": "payment.downtime",
            "id": "down_live_hdfc_001",
            "method": "netbanking",
            "bank": "HDFC",
            "scheduled": False,
            "severity": "high",
            "status": "started",
            "begin": int(datetime.now(timezone.utc).timestamp()),
            "end": int(datetime.now(timezone.utc).timestamp()) + 7200,
            "instrument": {"bank": "HDFC"},
            "created_at": int(datetime.now(timezone.utc).timestamp()),
        }
        (GOLDEN_DIR / "razorpay_downtime_entity.json").write_text(json.dumps(downtime_fixture, indent=2), encoding="utf-8")
        print(f"Captured: {GOLDEN_DIR / 'razorpay_downtime_entity.json'}")

    print(f"\nSuccessfully populated {GOLDEN_DIR} with grounded Razorpay API contracts.")


if __name__ == "__main__":
    capture_all()
