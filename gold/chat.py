import json
import re
from datetime import timedelta
from uuid import uuid4

from . import calendar_terms
from .routing import local_intent, normalize
from .sips import Plans, describe
from .store import Problem, amount, fixed

ANSWERS = {
    "sell_info": "Simplify Money describes a seven-day hold before selling a purchase. This simulator supports buying and viewing holdings. You can ask how much gold you own.",
    "gift_info": "Simplify Money offers gifting in its app. This simulator credits purchases to the authenticated buyer. You can review your own gold holdings here.",
    "other_asset": "I can explain a comparison with gold. For a purchase or recurring plan in another asset, use that product’s own flow.",
    "expense_info": "I can total your confirmed gold purchases here. I have no linked bank or food-spending records to calculate your other expenses.",
    "sip_info": "A gold SIP spends a fixed rupee amount on each due date. The grams vary with the price. You can review the amount, frequency and first date before starting.",
    "decline": "Understood. No transaction or plan change was made.",
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
    text = re.sub(r"\b(?:22|24)\s*(?:k|karat|carat)\b", "", text)
    text = re.sub(r"\b(?:rs\.?|inr)(?=\d)", "₹", text)
    if re.search(r"\d+\.\d+\.\d", text):
        raise Problem(422, "Please use one decimal point in the INR amount.")
    numbers = re.findall(r"(?<![\w.])[-+−]?(?:\d+(?:,\d+)*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?", text)
    if len(numbers) != 1:
        return None
    raw = numbers[0]
    signed_currency = r"[-−]\s*(?:₹|rs\.?|inr)\s*\d|[-−]\s+\d"
    non_rupee_amount = r"\d\s*(?:grams?|kg|g|k|thousands?|lakhs?|crores?)\b|\b(?:usd|gbp|eur|aed|btc|bitcoins?|dollars?|euros?|pounds?)\b|[$€£]"
    if re.search(signed_currency, text) or re.search(non_rupee_amount, text):
        raise Problem(422, "Please give the full INR amount in digits, for example ₹500.")
    if "," in raw and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d{1,2})?", raw):
        raise Problem(422, "Please check the commas in the INR amount.")
    return fixed(amount(raw.replace(",", "")), 2)


def action(path, body, key=None):
    return {"method": "POST", "path": path, "body": body, "idempotency_key": key or uuid4().hex}


class Conversation:
    def __init__(self, store, groq=None):
        self.store = store
        self.plans = Plans(store)
        self.groq = groq

    def reply(self, owner, message, key):
        text = normalize(message)
        route = local_intent(text)
        # Classify unfamiliar language outside the writer lock. Local checks own amounts and permissions.
        source = "local"
        if self.groq and route in {"other", "gold", "purchase", "quote", "risk", "education", "compare", "unclear"}:
            permitted = self.store.reserve_model_call(owner, key)
            predicted = self.groq.classify(message) if permitted else None
            if predicted and (route == "other" or predicted == route or route == "gold"):
                route, source = predicted, "groq"
            elif predicted is None:
                source = "local_fallback"

        def respond(db):
            intent = route
            row = db.execute("SELECT terms FROM sip_drafts WHERE owner=? AND expires>?",
                             (owner, self.store.now().isoformat())).fetchone()
            draft = {}
            if row and calendar_terms.is_followup(text):
                intent, draft = "sip", json.loads(row["terms"])
            db.execute("DELETE FROM sip_drafts WHERE owner=?", (owner,))
            if intent != "sip" and re.fullmatch(r"(?:₹|rs\.?|inr)?\s*[0-9,]+(?:\.\d+)?(?:\s*rupees?)?", text):
                prior = db.execute("""SELECT details FROM events WHERE owner=? AND event='conversation'
                    ORDER BY seq DESC LIMIT 1""", (owner,)).fetchone()
                if prior:
                    previous = json.loads(prior["details"])["result"]
                    if previous["intent"] in ("purchase", "quote", "recover") and previous["action"] is None:
                        intent = "quote"
            try:
                reply, card = self.answer(db, owner, text, intent, draft)
            except Problem as exc:
                if exc.status != 422:
                    raise
                reply, card = str(exc), None
            self.store.event(db, owner, "message_routed", intent=intent, source=source)
            return {"intent": intent, "message": reply, "action": card}
        return self.store.command(owner, key, "conversation", message, respond)

    def answer(self, db, owner, text, route, draft):
        if route == "rate":
            rate, *_ = self.store.price_terms()
            return f"The configured simulation rate is ₹{fixed(rate, 2)} per gram before fees and GST.", None
        if route == "holdings":
            total = self.store.holdings(db, owner)
            return (f"You own {total['grams']} g in this simulated ledger. You paid ₹{total['total_paid']} "
                    f"across {total['purchases']} completed purchases and instalments."), None
        if route == "withdraw":
            count = self.store.withdraw_quotes(db, owner)
            return f"Withdrew {count} open purchase quote(s). Completed purchases remain in your ledger.", None
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
                reply, body = calendar_terms.collect(text, self.plans.today(), value, draft)
                if body:
                    return reply, action("/sips", body)
                expires = (self.store.now() + timedelta(minutes=5)).isoformat()
                db.execute("INSERT INTO sip_drafts VALUES (?,?,?)", (owner, json.dumps(draft), expires))
                return reply, None
            if not value:
                return "How many rupees would you like me to quote? For example, buy ₹500 of gold.", None
            card = self.store.new_quote(db, owner, value)
        confirmation = action("/purchases", {"quote_id": card["id"]}, card["id"])
        confirmation["quote"] = card
        parts = card["breakdown"]
        return (f"Review {card['grams']} g at ₹{card['inr_per_gram']}/g. Gold ₹{parts['gold_value']}, "
                f"GST ₹{parts['gst']}, platform fee ₹{parts['platform_fee']}. Total ₹{card['amount']}. "
                f"Confirm by {card['expires_at']}."), confirmation
