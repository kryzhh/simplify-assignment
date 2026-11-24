"""Durable commands. All writes for one command share a SQLite transaction."""
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


class Problem(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def paise(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", value):
        raise Problem(422, "Use an INR decimal with at most two fractional digits.")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def amount(value):
    result = paise(value)
    if not 1000 <= result <= 5_000_000:
        raise Problem(422, "Choose an amount from ₹10.00 to ₹50,000.00.")
    return result


def fixed(value, places):
    scale = 10 ** places
    return f"{value // scale}.{value % scale:0{places}d}"


def costing(paise_value, rate):
    units = paise_value * 10_000 // rate
    if units == 0:
        raise Problem(422, "This amount buys less than 0.0001 g.")
    return units


def display(row):
    return {"id": row["id"], "amount": fixed(row["paise"], 2),
            "inr_per_gram": fixed(row["rate"], 2), "grams": fixed(row["units"], 4)}


def receipt(row):
    return {**display(row), "created_at": row["created"], "quote_id": row["quote_id"],
            "sip_id": row["sip_id"], "due_on": row["due"]}


def quote_card(row):
    return {**display(row), "expires_at": row["expires"], "action": "confirm_purchase"}


class Store:
    def __init__(self, path, price_path, clock=None):
        self.path = Path(path)
        self.price_path = Path(price_path)
        self.clock = clock or (lambda: datetime.now(UTC))

    def now(self):
        return self.clock().astimezone(UTC)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=8, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()  # Closing an uncommitted transaction rolls it back.

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text())

    def issue_token(self, owner):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner):
            raise ValueError("Use a pseudonymous user ID of 1 to 64 ASCII letters, digits, _ or -.")
        token = secrets.token_urlsafe(32)
        with self.connection(True) as db:
            db.execute("INSERT INTO credentials VALUES (?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), owner))
        return token

    def authenticate(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute("SELECT owner FROM credentials WHERE digest=?", (digest,)).fetchone()
        if row is None:
            raise Problem(401, "Invalid bearer credential.")
        return row["owner"]

    def rate(self):
        try:
            value = paise(json.loads(self.price_path.read_text())["inr_per_gram"])
            if value <= 0:
                raise ValueError
            return value
        except (OSError, KeyError, ValueError, TypeError, Problem) as exc:
            raise Problem(503, "Gold price unavailable. Please retry later.") from exc

    def event(self, db, owner, name, **details):
        db.execute("INSERT INTO events(time,owner,event,details) VALUES (?,?,?,?)",
                   (self.now().isoformat(), owner, name, json.dumps(details, ensure_ascii=False)))

    def trace(self, owner, after=0, limit=100):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM events WHERE owner=? AND seq>? ORDER BY seq LIMIT ?",
                              (owner, after, limit))
            return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def command(self, owner, key, operation, payload, apply):
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise Problem(422, "Invalid Idempotency-Key.")
        fingerprint = hashlib.sha256(json.dumps([operation, payload], sort_keys=True).encode()).hexdigest()
        try:
            with self.connection(True) as db:
                old = db.execute("SELECT * FROM requests WHERE owner=? AND key=?", (owner, key)).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise Problem(409, "Key already belongs to another command.")
                    self.event(db, owner, "replayed", operation=operation, key=key)
                    return json.loads(old["result"])
                result = apply(db)
                db.execute("INSERT INTO requests VALUES (?,?,?,?)",
                           (owner, key, fingerprint, json.dumps(result)))
                self.event(db, owner, operation, key=key, result=result)
                return result
        except Problem as exc:
            with self.connection(True) as db:
                self.event(db, owner, "command_failed", operation=operation, key=key, reason=str(exc))
            raise

    def new_quote(self, db, owner, value):
        p = amount(value)
        rate = self.rate()
        now = self.now()
        row = {"id": uuid4().hex, "owner": owner, "paise": p, "rate": rate,
               "units": costing(p, rate), "expires": (now + timedelta(minutes=5)).isoformat(),
               "created": now.isoformat()}
        db.execute("INSERT INTO quotes VALUES (:id,:owner,:paise,:rate,:units,:expires,:created)", row)
        return quote_card(row)

    def quote(self, owner, value, key):
        return self.command(owner, key, "quote", value, lambda db: self.new_quote(db, owner, value))

    def pending(self, db, owner):
        row = db.execute("""SELECT q.* FROM quotes q LEFT JOIN ledger l ON l.quote_id=q.id
            WHERE q.owner=? AND q.expires>? AND l.id IS NULL
            ORDER BY q.created DESC, q.rowid DESC LIMIT 1""", (owner, self.now().isoformat())).fetchone()
        return quote_card(row) if row else None

    def buy(self, owner, quote_id, key):
        def confirm(db):
            row = db.execute("SELECT * FROM quotes WHERE id=? AND owner=?", (quote_id, owner)).fetchone()
            if row is None:
                raise Problem(404, "Quote not found.")
            previous = db.execute("SELECT * FROM ledger WHERE quote_id=?", (quote_id,)).fetchone()
            if previous:
                return receipt(previous)
            if row["expires"] <= self.now().isoformat():
                raise Problem(409, "Quote expired. Request a new price.")
            return self.book(db, row, quote_id=quote_id)
        return self.command(owner, key, "purchase", quote_id, confirm)

    def book(self, db, priced, quote_id=None, sip_id=None, due=None):
        row = {**dict(priced), "id": uuid4().hex, "created": self.now().isoformat(),
               "quote_id": quote_id, "sip_id": sip_id, "due": due}
        db.execute("""INSERT INTO ledger VALUES
            (:id,:owner,:paise,:rate,:units,:created,:quote_id,:sip_id,:due)""", row)
        return receipt(row)

    def ledger(self, owner, limit=100, offset=0):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM ledger WHERE owner=? ORDER BY created DESC, rowid DESC LIMIT ? OFFSET ?",
                              (owner, limit, offset))
            return [receipt(row) for row in rows]
