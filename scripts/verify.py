"""Replay an isolated HTTP journey with an injected calendar; works inside the API image."""
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory

from gold.sips import Plans
from gold.store import Store


def walkthrough(verbose=True):
    import uvicorn
    from gold.api import create_app

    with TemporaryDirectory() as tmp, socket.socket() as listener:
        now = datetime(2026, 11, 24, 9, tzinfo=UTC)
        price = Path(tmp, "price.json")
        price.write_text('{"inr_per_gram":"6000.00"}')
        store = Store(Path(tmp, "demo.sqlite"), price, lambda: now)
        store.initialize()
        alice = store.issue_token("demo-alice")
        bob = store.issue_token("demo-bob")
        # Keep the demo offline even if the running service has a Groq credential.
        app = create_app(store=store, groq=False, run_scheduler=False)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()

        def call(path, body=None, key=None, token=alice, expected=200):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            if key:
                headers["Idempotency-Key"] = key
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.request("GET" if body is None else "POST", path,
                             None if body is None else json.dumps(body).encode(), headers)
                response = conn.getresponse()
                result = json.loads(response.read())
                if response.status != expected:
                    raise AssertionError(f"{path}: expected {expected}, got {response.status}: {result}")
                return result
            finally:
                conn.close()

        def check(label, passed, result=None):
            if not passed:
                raise AssertionError(label)
            if verbose:
                print(label, json.dumps(result, ensure_ascii=False) if result is not None else "")

        def confirm(card):
            return call(card["path"], card["body"], card["idempotency_key"])

        try:
            deadline = time.monotonic() + 8
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("HTTP server failed to start")
                time.sleep(0.02)
            check("API ready", call("/health")["status"] == "ok")
            call("/ledger", token=None, expected=401)
            call("/chat", {"message": "x" * 10000}, "big", expected=413)
            question = call("/chat", {"message": "Should I buy gold or put it in an FD?"}, "q")
            check("Answered comparison", question["intent"] == "compare", question["message"])
            card = call("/chat", {"message": "Buy gold worth 333.33 rupees"}, "price")["action"]
            recovered = call("/chat", {"message": "Send it again"}, "recover")["action"]
            check("Recovered original card", card == recovered)
            call("/purchases", card["body"], "wrong-user", bob, 404)
            trade = confirm(card)
            check("One-time receipt", trade["amount"] == "333.33" and trade["grams"] == "0.0555", trade)
            check("Replay returned original receipt", confirm(card) == trade)
            call("/quotes", {"amount": "100"}, "price", expected=409)
            proposal = call("/chat", {"message": "SIP of Rs 100 daily"}, "proposal")["action"]
            plan = confirm(proposal)
            check("Created daily SIP once", confirm(proposal) == plan, plan)
            now += timedelta(days=2)
            count = Plans(store).run_due()
            ledger = call("/ledger")
            check("Three instalments booked", count == 3 and len(ledger) == 4,
                  sorted(r["due_on"] for r in ledger if r["sip_id"]))
            call(f"/sips/{plan['id']}/pause", {}, "pause")
            call(f"/sips/{plan['id']}/cancel", {}, "cancel")
            check("Other user ledger is empty", call("/ledger", token=bob) == [])
            price.unlink()
            call("/quotes", {"amount": "100"}, "no-price", expected=503)
            trace = call("/events")
            check("Trace reconstructs purchase, instalments and outage",
                  sum(e["event"] == "instalment" for e in trace) == 3 and
                  any(e["event"] == "purchase" for e in trace) and trace[-1]["event"] == "command_failed")
            if verbose:
                for event in trace:
                    print(json.dumps(event, ensure_ascii=False))
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError("HTTP server failed to stop")


if __name__ == "__main__":
    walkthrough()
