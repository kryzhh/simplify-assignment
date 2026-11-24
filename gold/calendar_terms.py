"""Collect SIP terms across short replies and resolve them on the Indian calendar."""
import re
from datetime import date, timedelta

from .sips import in_month, next_date

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY = "|".join(WEEKDAYS)
WHEN = rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)|today|tomorrow|yesterday|{DAY})\b"
FREQUENCY = {"daily": r"\bdaily\b|every day", "weekly": r"\bweekly\b|every week",
             "monthly": r"\bmonthly\b|every month"}


def is_followup(text):
    return re.fullmatch(rf"(?:starting |from |on |every |next )?(?:{WHEN}|daily|weekly|monthly|day|week|month)"
                        r"|(?:₹|rs\.?|inr)?\s*[\d,.]+(?:\s*rupees?)?", text) is not None


def collect(text, today, value, terms):
    """Return the next question or a complete confirmation payload. Persist only extracted terms."""
    if value:
        terms["amount"] = value
    choices = [name for name, pattern in FREQUENCY.items() if re.search(pattern, text)]
    dates = re.findall(WHEN, text)
    if re.search(rf"every (?:{DAY})\b", text):
        choices.append("weekly")
    if re.search(r"\b(biweekly|fortnightly|quarterly|yearly|annually|alternate|every other)\b|every \d+", text):
        terms.pop("frequency", None)
        return "I can schedule daily, weekly or monthly. Which frequency would you like?", None
    if len(set(choices)) > 1:
        terms.pop("frequency", None)
        return "Choose one frequency: daily, weekly or monthly.", None
    if choices:
        terms["frequency"] = choices[0]
    if len(dates) > 1 or (not dates and re.search(r"\b(starting|from|next|on)\b", text)):
        terms["when"] = "needs_date"
    elif dates:
        terms["when"] = dates[0]
        if re.search(rf"\bnext (?:{DAY})\b", text):
            terms["when"] = "next " + dates[0]
    when = terms.get("when", "today")
    if when in ("needs_date", "yesterday"):
        return "What is the first due date? Choose today or a future date (YYYY-MM-DD).", None
    if "amount" not in terms:
        return "How many rupees should each SIP instalment buy?", None
    if "frequency" not in terms:
        return f"How often should the ₹{terms['amount']} SIP run: daily, weekly or monthly?", None
    frequency = terms["frequency"]
    body = {"amount": terms["amount"], "frequency": frequency}
    start = today
    weekday = when.removeprefix("next ")
    if weekday in WEEKDAYS:
        delta = (WEEKDAYS.index(weekday) - today.weekday()) % 7
        start += timedelta(days=7 if delta == 0 and when.startswith("next ") else delta)
    elif when == "tomorrow":
        start += timedelta(days=1)
    elif re.fullmatch(r"\d{1,2}(st|nd|rd|th)", when):
        anchor = int(when[:-2])
        if frequency != "monthly" or not 1 <= anchor <= 31:
            terms["when"] = "needs_date"
            return "Please give the first due date as YYYY-MM-DD.", None
        start = in_month(today.year, today.month, anchor)
        if start < today:
            start = next_date(start, frequency, anchor)
        body["anchor_day"] = anchor
    elif when != "today":
        try:
            start = date.fromisoformat(when)
        except ValueError:
            terms["when"] = "needs_date"
            return "Please provide a valid date as YYYY-MM-DD.", None
    if not today <= start <= today + timedelta(days=3650):
        terms["when"] = "needs_date"
        return "Please choose a start between today and ten years from today.", None
    body["start"] = start.isoformat()
    return f"Review a {frequency} SIP of ₹{terms['amount']}, first due {start} (India time).", body
