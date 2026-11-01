import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SIGNATURE_HEADER = "x-pinhire-hmac-2510"
REFUND_LIMIT_AED = 520
IDEMPOTENCY_TTL_SECONDS = 120
MAX_BODY_BYTES = 1_048_576
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


class IdempotencyStore:
    def __init__(self, ttl_seconds=IDEMPOTENCY_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._expires_at = {}
        self._lock = threading.Lock()

    def claim(self, transaction_ref):
        now = time.monotonic()
        with self._lock:
            expired = [
                ref for ref, expires_at in self._expires_at.items()
                if expires_at <= now
            ]
            for ref in expired:
                del self._expires_at[ref]

            if transaction_ref in self._expires_at:
                return False

            self._expires_at[transaction_ref] = now + self._ttl_seconds
            return True


def _reject_json_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def _faq_answer(query):
    normalized_query = query.lower()
    if "attempt" in normalized_query or "again" in normalized_query:
        return "Each account gets one attempt."
    if "score" in normalized_query or "mark" in normalized_query:
        return "A correct answer earns 2 points, a wrong answer loses 1, and a blank earns 0."
    if "time" in normalized_query or "minute" in normalized_query:
        return "Start during the displayed start window; after starting, you have 60 minutes."
    return "Please check the official PinHire FAQ for details."


def process_request(raw_body, signature, signing_key, idempotency_store):
    expected_signature = hmac.new(
        signing_key, raw_body, hashlib.sha256
    ).hexdigest()
    if (
        not isinstance(signature, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", signature) is None
        or not hmac.compare_digest(expected_signature, signature.lower())
    ):
        return 401, {"status": "unauthorized"}

    try:
        request_data = json.loads(
            raw_body, parse_constant=_reject_json_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return 400, {"status": "invalid_json"}

    if not isinstance(request_data, dict):
        return 400, {"status": "invalid_payload"}

    payload = request_data.get("payload", request_data)
    if not isinstance(payload, dict):
        return 400, {"status": "invalid_payload"}

    transaction_ref = payload.get(
        "tx_ref_2510", request_data.get("tx_ref_2510")
    )
    if (
        isinstance(transaction_ref, bool)
        or not isinstance(transaction_ref, (str, int))
        or not str(transaction_ref).strip()
        or len(str(transaction_ref)) > 256
    ):
        return 400, {"status": "invalid_transaction_reference"}

    refund_aed = payload.get("refund_aed", request_data.get("refund_aed"))
    if refund_aed is not None:
        if (
            isinstance(refund_aed, bool)
            or not isinstance(refund_aed, (int, float))
            or (isinstance(refund_aed, float) and not math.isfinite(refund_aed))
            or refund_aed < 0
        ):
            return 422, {"status": "invalid_refund_amount"}
        if refund_aed > REFUND_LIMIT_AED:
            return 422, {"status": "refund_limit_exceeded"}

    if not idempotency_store.claim(str(transaction_ref).strip()):
        return 409, {"status": "duplicate"}

    event = request_data.get(
        "event",
        request_data.get("type", payload.get("event", payload.get("type", ""))),
    )
    if event == "faq.query":
        query = payload.get("query", request_data.get("query", ""))
        answer = _faq_answer(query) if isinstance(query, str) else (
            "Please check the official PinHire FAQ for details."
        )
        return 200, {"status": "processed", "answer": answer}

    response = {"status": "processed"}
    if refund_aed is not None:
        response["refund_aed"] = refund_aed
    return 200, response


def create_handler(signing_key, idempotency_store):
    class WebhookHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok"})
            else:
                self._send_json(404, {"status": "not_found"})

        def do_POST(self):
            if self.path != "/webhook":
                self._send_json(404, {"status": "not_found"})
                return

            content_length = self.headers.get("Content-Length")
            try:
                body_length = int(content_length)
            except (TypeError, ValueError):
                self._send_json(411, {"status": "content_length_required"})
                return

            if body_length < 0:
                self._send_json(400, {"status": "invalid_content_length"})
                return
            if body_length > MAX_BODY_BYTES:
                self._send_json(413, {"status": "payload_too_large"})
                return

            raw_body = self.rfile.read(body_length)
            status, response = process_request(
                raw_body,
                self.headers.get(SIGNATURE_HEADER),
                signing_key,
                idempotency_store,
            )
            self._send_json(status, response)

        def _send_json(self, status, response):
            encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format_string, *args):
            return

    return WebhookHandler


def main():
    seed_token = os.environ.get("PINHIRE_SEED_TOKEN")
    if not seed_token:
        raise SystemExit(
            "Set PINHIRE_SEED_TOKEN to the signing token shown for your seed."
        )

    host = os.environ.get("HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    except ValueError as error:
        raise SystemExit("PORT must be an integer.") from error
    if not 0 < port < 65536:
        raise SystemExit("PORT must be between 1 and 65535.")

    server = ThreadingHTTPServer(
        (host, port),
        create_handler(seed_token.encode("utf-8"), IdempotencyStore()),
    )
    print(f"Webhook listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


#power shell pai 
#Set-Location 'C:\Users\Icon\OneDrive\Desktop\PinHier\pinhire-webhook'.\.venv\Scripts\python.exe -m unittest -v    