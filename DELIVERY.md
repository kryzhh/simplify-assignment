# Delivery notes

## AI use

Codex (OpenAI) generated and edited the implementation, tests, verification script and documentation from the supplied assignment, chat feedback and purchase screenshots. The requester selected FastAPI and Groq. Groq is the application's runtime intent provider.

One generated parser initially rejected any message containing the word “grams”:

```python
if re.search(r"\b(grams?|kg|usd|dollars?|lakh|lakhs|crores?|thousand)\b|\d\s*(?:k|g)\b|[$€£]", text):
    raise Problem(422, "Please give the full INR amount in digits, for example ₹500.")
```

The regression case “How many grams of gold can I buy for ₹500?” returned no quote. There the rupee amount is the input and grams are the requested output unit. The correction ties the weight or multiplier to a number:

```python
signed_currency = r"[-−]\s*(?:₹|rs\.?|inr)\s*\d|[-−]\s+\d"
non_rupee_amount = r"\d\s*(?:grams?|kg|g|k|thousands?|lakhs?|crores?)\b|\b(?:usd|dollars?|euros?)\b|[$€£]"
if re.search(signed_currency, text) or re.search(non_rupee_amount, text):
    raise Problem(422, "Please give the full INR amount in digits, for example ₹500.")
```

The same test checks a numeric weight, an ambiguous shorthand, a signed currency and a non-INR amount. Both versions were AI-assisted.

## Verification and remaining work

* Local execution covered real SQLite transactions and concurrent writers, date progression, outages, user isolation, replay, chat examples, the confirmation-card recovery path, and the Groq HTTP adapter against simulated provider responses. Seventeen tests passed locally. Changing gold rounding to nearest in a temporary copy made the ₹333.33 regression test fail with 0.0556 g in place of 0.0555 g. The source checker and Python compilation also passed.
* This coding environment could not download FastAPI, Uvicorn, Bandit or pip-audit. The loopback HTTP walkthrough and full test suite require the installed packages. The Docker build, live Groq response and advisory-database scan also still need verification. The documented commands and CI jobs exercise these paths.
* Real money movement and gold custody require a payment provider and a custodian, a signed webhook inbox, reconciliation and a provider idempotency contract. This submission records simulated receipts only. It does not reproduce SafeGold fees or GST.
* The deployment target here is a single host with persistent local storage. Before serving customer traffic, provide TLS termination, token rotation and revocation, database backups and restore drills, audit retention, and operations monitoring. Multiple hosts would require a shared transactional store and coordinated scheduling.
* Runtime dependencies are pinned directly. A hash-locked transitive dependency set and a verified production image digest remain release work.
* The recording, applicant CV and non-code assignment documents are separate submission materials.
