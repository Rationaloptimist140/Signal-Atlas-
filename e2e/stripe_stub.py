"""Local stand-in for the parts of the Stripe API that Signal Atlas calls.

For end-to-end tests on a developer machine only. It lets the browser journey (checkout, return,
webhooks, cancellation, failed renewal) run without a Stripe account. It proves nothing about the
real Stripe service: run the same journey against Stripe test mode before relying on billing. Works on Python 3.9+.

    STRIPE_WEBHOOK_SECRET=whsec_stub WEBHOOK_URL=http://localhost:3000/api/v1/billing/webhooks/stripe python stripe_stub.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("STUB_PORT", "4242"))
SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_stub")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://localhost:3000/api/v1/billing/webhooks/stripe")
STATE = {"sessions": {}, "subscriptions": {}, "events": 0, "webhooks": True}
LOCK = threading.Lock()


def send_event(kind: str, obj: dict) -> None:
    if not STATE["webhooks"]:
        return
    with LOCK:
        STATE["events"] += 1
        event_id = f"evt_stub_{STATE['events']}"
    payload = json.dumps({"id": event_id, "type": kind, "livemode": False, "data": {"object": obj}}).encode()
    ts = int(time.time())
    signature = hmac.new(SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = urllib.request.Request(WEBHOOK_URL, data=payload, headers={"Stripe-Signature": f"t={ts},v1={signature}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def subscription_object(sub: dict) -> dict:
    return {"id": sub["id"], "customer": sub["customer"], "status": sub["status"], "cancel_at_period_end": sub["cancel_at_period_end"], "metadata": sub["metadata"],
            "items": {"data": [{"current_period_start": sub["start"], "current_period_end": sub["end"]}]}}


def invoice_object(sub: dict, invoice_id: str, paid: bool) -> dict:
    return {"id": invoice_id, "customer": sub["customer"], "currency": "gbp", "amount_paid": sub["amount"] if paid else 0, "amount_due": sub["amount"],
            "hosted_invoice_url": f"http://localhost:{PORT}/invoice/{invoice_id}", "status_transitions": {"paid_at": int(time.time()) if paid else None},
            "parent": {"subscription_details": {"subscription": sub["id"], "metadata": sub["metadata"]}},
            "lines": {"data": [{"description": sub["description"], "period": {"start": sub["start"], "end": sub["end"]}}]}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # keep test output quiet
        pass

    def _send(self, status: int, body, content_type: str = "application/json", headers: dict | None = None) -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if path == "/v1/balance":
            return self._send(200, {"object": "balance", "livemode": False})
        if path == "/v1/webhook_endpoints":
            return self._send(200, {"data": [{"url": WEBHOOK_URL.replace("http://localhost:3000", os.environ.get("PUBLIC_URL", "http://localhost:3000")), "status": "enabled", "enabled_events": ["*"]}]})
        if parts[:3] == ["v1", "checkout", "sessions"] and len(parts) == 4 and parts[3] in STATE["sessions"]:
            return self._send(200, STATE["sessions"][parts[3]]["object"])
        if parts[:2] == ["v1", "subscriptions"] and len(parts) == 3 and parts[2] in STATE["subscriptions"]:
            return self._send(200, subscription_object(STATE["subscriptions"][parts[2]]))
        if parts[0] == "pay" and len(parts) == 2 and parts[1] in STATE["sessions"]:
            session = STATE["sessions"][parts[1]]
            html = (f"<!doctype html><title>Stub checkout</title><body style='font-family:sans-serif;max-width:480px;margin:80px auto'>"
                    f"<h1>Stub checkout (not Stripe)</h1><p id='item'>{session['description']} &mdash; {session['amount'] / 100:.2f} GBP</p>"
                    f"<form method='post' action='/pay/{parts[1]}/complete'><button id='pay'>Pay with test card</button></form>"
                    f"<p><a id='cancel' href='{session['cancel_url']}'>Cancel and return</a></p></body>")
            return self._send(200, html, "text/html")
        if parts[0] in ("portal", "invoice"):
            return self._send(200, "<!doctype html><title>Stub</title><body><h1>Stub billing page (not Stripe)</h1></body>", "text/html")
        return self._send(404, {"error": {"type": "invalid_request_error", "message": f"stub: no such resource {path}"}})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        form = self._form()
        if path == "/v1/checkout/sessions":
            with LOCK:
                session_id = f"cs_test_stub{len(STATE['sessions']) + 1}"
            metadata = {k[len("metadata["):-1]: v for k, v in form.items() if k.startswith("metadata[")}
            obj = {"id": session_id, "object": "checkout.session", "mode": "subscription", "status": "open", "payment_status": "unpaid", "customer": None, "subscription": None,
                   "client_reference_id": form.get("client_reference_id"), "metadata": metadata}
            STATE["sessions"][session_id] = {"object": obj, "success_url": form["success_url"], "cancel_url": form["cancel_url"],
                                             "amount": int(form["line_items[0][price_data][unit_amount]"]), "interval": form["line_items[0][price_data][recurring][interval]"],
                                             "description": form["line_items[0][price_data][product_data][name]"], "customer_email": form.get("customer_email")}
            return self._send(200, {"id": session_id, "url": f"http://localhost:{PORT}/pay/{session_id}"})
        if parts[0] == "pay" and len(parts) == 3 and parts[2] == "complete" and parts[1] in STATE["sessions"]:
            session = STATE["sessions"][parts[1]]
            number = len(STATE["subscriptions"]) + 1
            now = int(time.time())
            sub = {"id": f"sub_stub{number}", "customer": f"cus_stub{number}", "status": "active", "cancel_at_period_end": False, "metadata": session["object"]["metadata"],
                   "start": now, "end": now + (365 if session["interval"] == "year" else 30) * 86400, "amount": session["amount"], "description": session["description"], "invoices": 1}
            STATE["subscriptions"][sub["id"]] = sub
            session["object"].update(status="complete", payment_status="paid", customer=sub["customer"], subscription=sub["id"])
            send_event("checkout.session.completed", session["object"])
            send_event("customer.subscription.created", subscription_object(sub))
            send_event("invoice.paid", invoice_object(sub, f"in_stub{number}_1", True))
            return self._send(303, "", "text/plain", {"Location": session["success_url"].replace("{CHECKOUT_SESSION_ID}", parts[1])})
        if parts[:2] == ["v1", "subscriptions"] and len(parts) == 3 and parts[2] in STATE["subscriptions"]:
            sub = STATE["subscriptions"][parts[2]]
            if "cancel_at_period_end" in form:
                sub["cancel_at_period_end"] = form["cancel_at_period_end"] == "true"
            send_event("customer.subscription.updated", subscription_object(sub))
            return self._send(200, subscription_object(sub))
        if path == "/v1/billing_portal/sessions":
            return self._send(200, {"url": f"http://localhost:{PORT}/portal/{form.get('customer')}"})
        # --- test controls (not part of Stripe) -------------------------------------------------
        if parts[0] == "_stub" and parts[1] == "webhooks":
            STATE["webhooks"] = parts[2] == "on"
            return self._send(200, {"webhooks": STATE["webhooks"]})
        if parts[0] == "_stub" and parts[1] in ("fail_renewal", "pay_renewal") and STATE["subscriptions"]:
            sub = list(STATE["subscriptions"].values())[int(parts[2]) - 1 if len(parts) > 2 else -1]
            if parts[1] == "fail_renewal":
                sub["invoices"] += 1
                sub["status"] = "past_due"
            else:
                sub["status"] = "active"
            number = sub["id"].removeprefix("sub_stub")
            send_event("invoice.paid" if parts[1] == "pay_renewal" else "invoice.payment_failed", invoice_object(sub, f"in_stub{number}_{sub['invoices']}", parts[1] == "pay_renewal"))
            return self._send(200, {"status": sub["status"]})
        return self._send(404, {"error": {"type": "invalid_request_error", "message": f"stub: unsupported {path}"}})


if __name__ == "__main__":
    print(f"Stripe stub listening on http://localhost:{PORT} (webhooks -> {WEBHOOK_URL})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
