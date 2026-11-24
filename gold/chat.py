import json
import re
from datetime import date, timedelta
from uuid import uuid4

from .routing import local_intent
from .sips import Plans, describe, in_month, next_date
from .store import Problem, amount, fixed

ANSWERS = {
    "gold": "Would you like to learn how digital gold works, compare risks, or see a rupee quote?",
    "education": "Digital gold represents a quantity held for you by a provider. Check its custody, fees and redemption terms. I can show a simulated INR quote.",
    "risk": "Gold can lose value, even over a period when you need the money. What time horizon do you have in mind? I can show how a small purchase is priced.",
    "compare": "Gold changes in market value. An FD has an agreed interest rate and term. When will you need the money, and how important is predictability?",
    "tax": "ITR deadlines depend on the assessment year, filing category and extensions. Check the Income Tax Department portal for your category.",
    "other": "I can help with digital gold prices, purchases and recurring plans. What would you like to do?",
    "unclear": "What would you like to invest in? If you mean gold, tell me the INR amount and whether this is a one-time purchase or a SIP.",
    "blocked": "Purchases require a valid priced quote and your confirmation. I can help with a regular gold quote.",
}


def request_body(text):
    # Strip date expressions before looking for money. A day-of-month is never an amount.
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}(?:st|nd|rd|th)\b", "", text)
    numbers = re.findall(r"(?<![\w.])[-+−]?(?:\d+(?:,\d+)*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?", text)
    if len(numbers) != 1:
        return None
    raw = numbers[0]
    signed_currency = r"[-−]\s*(?:₹|rs\.?|inr)\s*\d|[-−]\s+\d"
    non_rupee_amount = r"\d\s*(?:grams?|kg|g|k|thousands?|lakhs?|crores?)\b|\b(?:usd|dollars?|euros?)\b|[$€£]"
    if re.search(signed_currency, text) or re.search(non_rupee_amount, text):
        raise Problem(422, "Please give the full INR amount in digits, for example ₹500.")
    if "," in raw and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d{1,2})?", raw):
        raise Problem(422, "Please check the commas in the INR amount.")
    return fixed(amount(raw.replace(",", "")), 2)


def plan_terms(text, today, value):
    frequencies = [f for f, rx in (("daily", r"daily|every day"), ("weekly", r"weekly|every week"),
                    ("monthly", r"monthly|every month")) if re.search(rx, text)]
    if not value or len(frequencies) != 1:
        return "What INR amount and frequency (daily, weekly or monthly) should I use?", None
    frequency = frequencies[0]
    body = {"amount": value, "frequency": frequency}
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    ordinal = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", text)
    if "yesterday" in text:
        return "The first instalment must be today or later. Which future date should I use?", None
    start = today + timedelta(days=1) if "tomorrow" in text else today
    if iso:
        try:
            start = date.fromisoformat(iso[0])
        except ValueError:
            return "Please provide a valid start date as YYYY-MM-DD.", None
    elif ordinal:
        anchor = int(ordinal[1])
        if frequency != "monthly" or not 1 <= anchor <= 31:
            return "Please give the first due date as YYYY-MM-DD.", None
        start = in_month(today.year, today.month, anchor)
        if start < today:
            start = next_date(start, frequency, anchor)
        body["anchor_day"] = anchor
    elif re.search(r"\b(starting|from|on|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text) and not re.search(r"\b(today|tomorrow)\b", text):
        return "What is the first due date? Please use YYYY-MM-DD.", None
    if start < today:
        return "Choose today or a future start date.", None
    body["start"] = start.isoformat()
    return f"Review a {frequency} SIP of ₹{value}, first due {start} (India time).", action("/sips", body)


def action(path, body, key=None):
    return {"method": "POST", "path": path, "body": body, "idempotency_key": key or uuid4().hex}


class Conversation:
    def __init__(self, store, groq=None):
        self.store = store
        self.plans = Plans(store)
        self.groq = groq

    def reply(self, owner, message, key):
        text = " ".join(message.lower().split())
        route = local_intent(text)
        # Classify unfamiliar language outside the writer lock. Local checks own amounts and permissions.
        source = "local"
        if self.groq and route not in {"blocked", "recover", "pause", "cancel", "sip"}:
            permitted = self.store.reserve_model_call(owner, key)
            predicted = self.groq.classify(message) if permitted else None
            if predicted and (route == "other" or predicted == route or route == "gold"):
                route, source = predicted, "groq"
            elif predicted is None:
                source = "local_fallback"

        def respond(db):
            intent = route
            if re.fullmatch(r"(?:₹|rs\.?|inr)?\s*[0-9,]+(?:\.\d+)?(?:\s*rupees?)?", text):
                prior = db.execute("""SELECT details FROM events WHERE owner=? AND event='conversation'
                    ORDER BY seq DESC LIMIT 1""", (owner,)).fetchone()
                if prior:
                    previous = json.loads(prior["details"])["result"]
                    if previous["intent"] in ("purchase", "quote", "recover") and previous["action"] is None:
                        intent = "quote"
            try:
                reply, card = self.answer(db, owner, text, intent)
            except Problem as exc:
                if exc.status != 422:
                    raise
                reply, card = str(exc), None
            self.store.event(db, owner, "message_routed", intent=intent, source=source)
            return {"intent": intent, "message": reply, "action": card}
        return self.store.command(owner, key, "conversation", message, respond)

    def answer(self, db, owner, text, route):
        if route in ANSWERS:
            return ANSWERS[route], None
        if route in {"pause", "cancel"}:
            rows = db.execute("""SELECT * FROM sips WHERE owner=? AND
                (state='active' OR (?='cancel' AND state='paused')) ORDER BY rowid DESC LIMIT 2""",
                              (owner, route)).fetchall()
            if len(rows) != 1:
                return ("Choose a SIP from GET /sips." if rows else "There is no eligible SIP."), None
            plan = describe(rows[0])
            return f"Confirm {route} for your {plan['frequency']} ₹{plan['amount']} SIP.", action(
                f"/sips/{plan['id']}/{route}", {})
        if route == "recover":
            card = self.store.pending(db, owner)
            if card is None:
                return "There is no unexpired purchase card. What INR amount should I quote?", None
        else:
            value = request_body(text)
            if route == "sip":
                return plan_terms(text, self.plans.today(), value)
            if not value:
                return "How many rupees would you like me to quote? For example, buy ₹500 of gold.", None
            card = self.store.new_quote(db, owner, value)
        confirmation = action("/purchases", {"quote_id": card["id"]}, card["id"])
        confirmation["quote"] = card
        return f"₹{card['amount']} buys {card['grams']} g at ₹{card['inr_per_gram']}/g. Confirm this quote within five minutes.", confirmation
