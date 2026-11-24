import calendar
from datetime import date, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .store import Problem, amount, costing, fixed

IST = ZoneInfo("Asia/Kolkata")
FREQUENCIES = ("daily", "weekly", "monthly")


def in_month(year, month, anchor):
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def next_date(due, frequency, anchor):
    if frequency == "monthly":
        return in_month(due.year + (due.month == 12), due.month % 12 + 1, anchor)
    return due + timedelta(days=7 if frequency == "weekly" else 1)


def describe(row):
    return {"id": row["id"], "amount": fixed(row["paise"], 2), "frequency": row["frequency"],
            "anchor_day": row["anchor"], "next_due": row["due"] if row["state"] == "active" else None,
            "state": row["state"]}


class Plans:
    def __init__(self, store):
        self.store = store

    def today(self):
        return self.store.now().astimezone(IST).date()

    def create(self, owner, value, frequency, start, key, anchor_day=None):
        payload = [value, frequency, start.isoformat(), anchor_day]

        def insert(db):
            paise_value = amount(value)
            if frequency not in FREQUENCIES:
                raise Problem(422, "Choose daily, weekly or monthly.")
            if not self.today() <= start <= self.today() + timedelta(days=3650):
                raise Problem(422, "Choose a start from today through the next ten years (India time).")
            anchor = start.day if anchor_day is None else anchor_day
            if not 1 <= anchor <= 31 or (anchor_day is not None and
                    (frequency != "monthly" or in_month(start.year, start.month, anchor) != start)):
                raise Problem(422, "Monthly anchor day must agree with the first due date.")
            row = {"id": uuid4().hex, "owner": owner, "paise": paise_value, "frequency": frequency,
                   "anchor": anchor, "due": start.isoformat(), "state": "active"}
            db.execute("INSERT INTO sips VALUES (:id,:owner,:paise,:frequency,:anchor,:due,:state)", row)
            return describe(row)
        return self.store.command(owner, key, "sip_created", payload, insert)

    def list(self, owner, limit=100, offset=0):
        with self.store.connection() as db:
            return [describe(row) for row in db.execute(
                "SELECT * FROM sips WHERE owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?", (owner, limit, offset))]

    def change(self, owner, plan_id, action, key):
        if action not in ("pause", "cancel"):
            raise Problem(422, "Choose pause or cancel.")

        def update(db):
            row = db.execute("SELECT * FROM sips WHERE id=? AND owner=?", (plan_id, owner)).fetchone()
            if row is None:
                raise Problem(404, "SIP not found.")
            if row["state"] == "cancelled" and action == "pause":
                raise Problem(409, "This SIP is already cancelled.")
            state = "paused" if action == "pause" else "cancelled"
            db.execute("UPDATE sips SET state=? WHERE id=?", (state, plan_id))
            return describe({**dict(row), "state": state})
        return self.store.command(owner, key, "sip_" + action, plan_id, update)

    def run_due(self, limit=100):
        """Catch up oldest due dates, with a commit between each instalment."""
        count = 0
        while count < limit:
            with self.store.connection(True) as db:
                row = db.execute("""SELECT * FROM sips WHERE state='active' AND due<=?
                    ORDER BY due, id LIMIT 1""", (self.today().isoformat(),)).fetchone()
                if row is None:
                    break
                try:
                    rate = self.store.rate()
                    units = costing(row["paise"], rate)
                except Problem as exc:
                    self.store.event(db, row["owner"], "instalment_deferred",
                                     sip_id=row["id"], due=row["due"], reason=str(exc))
                    break
                due = date.fromisoformat(row["due"])
                future = next_date(due, row["frequency"], row["anchor"])
                result = self.store.book(db, {**dict(row), "rate": rate, "units": units},
                                         sip_id=row["id"], due=row["due"])
                db.execute("UPDATE sips SET due=? WHERE id=?", (future.isoformat(), row["id"]))
                self.store.event(db, row["owner"], "instalment", receipt=result, next_due=future.isoformat())
                count += 1
        return count
