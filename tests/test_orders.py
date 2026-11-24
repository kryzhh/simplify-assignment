import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gold.store import Store, Problem


class Orders(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.price = Path(tmp.name, "price.json")
        self.price.write_text('{"inr_per_gram":"6000.00"}')
        self.now = datetime(2026, 11, 24, 10, tzinfo=UTC)
        self.store = Store(Path(tmp.name, "gold.db"), self.price, lambda: self.now)
        self.store.initialize()

    def test_fractional_purchase_rounds_down_and_is_spent_once(self):
        quote = self.store.quote("alice", "333.33", "quote-1")
        self.assertEqual(quote["grams"], "0.0555")
        self.assertEqual(quote["amount"], "333.33")
        with ThreadPoolExecutor(4) as pool:
            receipts = list(pool.map(lambda i: self.store.buy("alice", quote["id"], str(i)), range(8)))
        self.assertEqual(len({r["id"] for r in receipts}), 1)
        self.assertEqual(len(self.store.ledger("alice")), 1)

    def test_replay_survives_restart_and_missing_price(self):
        card = self.store.quote("alice", "10", "q")
        self.price.unlink()
        restarted = Store(self.store.path, self.price, lambda: self.now)
        self.assertEqual(restarted.quote("alice", "10", "q"), card)
        self.assertEqual(restarted.buy("alice", card["id"], "pay")["grams"], "0.0016")
        with self.assertRaises(Problem) as unavailable:
            restarted.quote("alice", "10", "new")
        self.assertEqual(unavailable.exception.status, 503)
        self.assertEqual(restarted.trace("alice")[-1]["event"], "command_failed")

    def test_quote_has_owner_expiry_and_payload_binding(self):
        card = self.store.quote("alice", "10", "q")
        for op, status in [(lambda: self.store.buy("bob", card["id"], "p"), 404),
                           (lambda: self.store.quote("alice", "500", "q"), 409)]:
            with self.assertRaises(Problem) as rejected:
                op()
            self.assertEqual(rejected.exception.status, status)
        self.now += timedelta(minutes=5)
        with self.assertRaisesRegex(Problem, "expired"):
            self.store.buy("alice", card["id"], "p")
        self.assertEqual(self.store.ledger("alice"), [])

    def test_credential_scopes_survive_restart(self):
        token = self.store.issue_token("a")
        other = self.store.issue_token("b")
        self.assertEqual(self.store.authenticate(token), "a")
        self.assertEqual(self.store.authenticate(other), "b")
        with self.assertRaisesRegex(Problem, "Invalid bearer"):
            self.store.authenticate(token + "x")
        with self.assertRaises(ValueError):
            self.store.issue_token("bad/user")

    def test_product_preview_is_locked_and_matches_the_receipt(self):
        self.store.price_path = Path("fixtures/price.json")
        q = self.store.quote("a", "10", "q")
        self.assertEqual(q["breakdown"], {"gold_value": "8.56", "gst": "0.44", "platform_fee": "1.00"})
        self.assertEqual(q["grams"], "0.0006")
        self.store.price_path = self.price
        self.assertEqual(self.store.buy("a", q["id"], "p")["breakdown"], q["breakdown"])
        self.assertEqual(self.store.ledger("a")[0]["breakdown"], q["breakdown"])

    def test_public_example_without_platform_fee(self):
        self.price.write_text('{"inr_per_gram":"6000", "pricing":{"gold_gst_bps":300}}')
        q = self.store.quote("a", "500", "q")
        self.assertEqual(q["breakdown"], {"gold_value": "485.44", "gst": "14.56", "platform_fee": "0.00"})
        self.assertEqual(q["grams"], "0.0809")
