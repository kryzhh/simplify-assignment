from datetime import UTC, date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from tempfile import TemporaryDirectory
from pathlib import Path

from gold.store import Store, Problem
from gold.sips import Plans


class Sips(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = datetime(2027, 1, 31, 12, tzinfo=UTC)
        self.price = Path(tmp.name, "price")
        self.price.write_text('{"inr_per_gram":"10000.00"}')
        self.store = Store(Path(tmp.name, "ledger"), self.price, lambda: self.now)
        self.store.initialize()
        self.plans = Plans(self.store)

    def test_month_end_recovers_anchor_and_multiple_workers_cannot_duplicate(self):
        args = ("alice", "500", "monthly", date(2027, 1, 31), "start")
        plan = self.plans.create(*args)
        self.assertEqual(plan, self.plans.create(*args))
        self.now = datetime(2027, 3, 31, 8, tzinfo=UTC)
        with ThreadPoolExecutor(3) as pool:
            counts = list(pool.map(lambda _: self.plans.run_due(), range(3)))
        self.assertEqual(sum(counts), 3)
        ledger = self.store.ledger("alice")
        self.assertEqual(sorted(r["due_on"] for r in ledger), ["2027-01-31", "2027-02-28", "2027-03-31"])
        self.assertTrue(all(r["grams"] == "0.0500" and r["sip_id"] == plan["id"] for r in ledger))

    def test_outage_retries_and_paused_or_cancelled_plans_do_not_execute(self):
        plan = self.plans.create("a", "100", "daily", self.plans.today(), "a")
        self.price.unlink()
        self.assertEqual(self.plans.run_due(), 0)
        self.assertEqual(self.store.trace("a")[-1]["event"], "instalment_deferred")
        self.price.write_text('{"inr_per_gram":"6000"}')
        self.assertEqual(self.plans.run_due(), 1)
        self.plans.change("a", plan["id"], "pause", "pause")
        self.now += timedelta(days=2)
        self.assertEqual(self.plans.run_due(), 0)
        self.plans.change("a", plan["id"], "cancel", "cancel")
        self.assertEqual(self.plans.list("a")[0]["state"], "cancelled")
        with self.assertRaises(Problem):
            self.plans.change("other", plan["id"], "pause", "x")

    def test_past_start_rejected_and_dates_follow_indian_midnight(self):
        self.now = datetime(2027, 1, 31, 19, tzinfo=UTC)
        with self.assertRaises(Problem):
            self.plans.create("a", "100", "weekly", date(2027, 1, 31), "past")
        self.plans.create("a", "100", "weekly", date(2027, 2, 1), "ok")
        self.assertEqual(self.plans.run_due(), 1)
        self.assertEqual(self.plans.list("a")[0]["next_due"], "2027-02-08")

    def test_too_small_instalment_does_not_block_a_larger_purchase(self):
        self.price.write_text('{"inr_per_gram":"110000.00"}')
        self.plans.create("small", "10", "daily", self.plans.today(), "sm")
        self.plans.create("large", "110", "daily", self.plans.today(), "lg")
        self.assertEqual(self.plans.run_due(), 1)
        self.assertEqual(len(self.store.ledger("large")), 1)
        self.assertEqual(self.store.ledger("small"), [])

    def test_deferred_retry_persists_across_worker_passes(self):
        self.price.write_text('{"inr_per_gram":"110000.00"}')
        self.plans.create("small", "10", "daily", self.plans.today(), "s")
        self.assertEqual(self.plans.run_due(limit=1), 0)
        self.plans.create("large", "110", "daily", self.plans.today(), "l")
        self.assertEqual(Plans(self.store).run_due(limit=1), 1)
        self.assertEqual(len(self.store.ledger("large")), 1)
        self.price.write_text('{"inr_per_gram":"10000.00"}')
        self.now += timedelta(minutes=1)
        self.assertEqual(self.plans.run_due(limit=1), 1)
        self.assertEqual(self.store.ledger("small")[0]["due_on"], self.plans.today().isoformat())
