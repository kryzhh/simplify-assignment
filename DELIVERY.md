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

* Docker Compose built the Python 3.13 image, started the API and scheduler, and passed the health check. All 24 tests passed inside the container. The separate HTTP walkthrough completed a purchase, replayed it, booked three SIP instalments, tested owner isolation, simulated a price outage and exported the trace. The walkthrough uses a temporary database.
* A synthetic request to the configured Groq model returned the expected comparison intent. Bandit and the source checker reported no findings at their configured thresholds. Pip-audit found no known advisories for the resolved runtime requirements at verification time.
* Changing gold rounding to nearest in a temporary copy made the ₹333.33 regression test fail with 0.0556 g in place of 0.0555 g. The bundled app-style pricing fixture also reproduces the observed ₹10 receipt. The fee assumptions are illustrative.
* Real money movement and gold custody would require payment and custody providers, verified webhook processing, reconciliation and provider-side idempotency. This service records simulated purchases.
* The deployment target here is a single host with persistent local storage. Before serving customer traffic, provide TLS termination, token rotation and revocation, database backups and restore drills, audit retention, and operations monitoring. Multiple hosts would require a shared transactional store and coordinated scheduling.
* Runtime dependencies are pinned directly. The base image and CI actions are pinned by digest or commit. Hash-locking the complete Python dependency graph and verifying the final release image remain release work.
* The recording, applicant CV and non-code assignment documents are separate submission materials.
