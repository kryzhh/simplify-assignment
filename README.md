# Digital gold backend

Ask about gold, get a five-minute INR quote, confirm it once, and inspect the receipt. A recurring plan books a separate ledger entry on every due date. The service uses FastAPI, Groq intent classification and SQLite. All transactions here are simulated.

## Run

From this directory, with Docker Compose installed:

```sh
docker compose up --build -d
docker compose exec api python -m gold issue-token demo
```

Open <http://127.0.0.1:8000/docs>, select **Authorize**, and paste the printed token. The API and scheduler start together. The named volume keeps credentials, quotes, receipts and audit events across restarts. Compose publishes the port on loopback.

For a local Python 3.13+ installation, run `./scripts/start`, then `.venv/bin/python -m gold issue-token demo` in another terminal. The first install needs access to PyPI. Local Python reads the process environment. Docker Compose also reads a local `.env` file.

### Enable Groq

Copy `.env.example` to `.env`, set `GROQ_API_KEY`, and run `docker compose up -d`. The default model is `openai/gpt-oss-20b`. Set `GROQ_MODEL` to select another model available to your account. With a key, Groq classifies eligible messages, including unfamiliar phrasing. The service sends only that message, with no ledger or user identifier. The model can return one intent label. The application supplies the response, quote and confirmation action. With no key, an invalid response, a timeout, or an exhausted request budget, the local router handles the conversation. [Groq chat API](https://console.groq.com/docs/api-reference) · [Groq model catalog](https://console.groq.com/docs/models)

## Verify

```sh
docker compose exec api python -m scripts.verify
docker compose exec api python -m unittest discover -v -s tests
```

The walkthrough boots a second copy of the actual API on an ephemeral loopback port and uses an isolated temporary database. It asks about gold versus an FD, recovers a missing buy card, confirms a ₹333.33 purchase, resends the confirmation, creates a ₹100 daily SIP, advances the test clock two days and runs the scheduler. It checks three instalments, pauses and cancels the plan, verifies user isolation, removes the price source, and prints one user's event log. The production API has no clock or scheduler override endpoint. For a recording, show the startup, the walkthrough, then the test command.

## Try a purchase

```sh
TOKEN=$(docker compose exec -T api python -m gold issue-token reviewer)
curl -sS http://127.0.0.1:8000/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: ask-001' \
  -d '{"message":"How much gold can I buy for 500 rupees?"}'
```

The reply contains an `action` with a method, path, JSON body and idempotency key. Show the quote to the user. After their explicit confirmation, POST the supplied body to the supplied path using their bearer token and the supplied `Idempotency-Key`. The response is a receipt. Recover a missing card with “send it again” or `GET /quotes/pending`.

| Endpoint | Behavior |
| --- | --- |
| `POST /chat` | Takes `{"message":"..."}`. An actionable answer carries a machine-readable purchase or SIP card. |
| `POST /quotes` | Takes a decimal string such as `{"amount":"333.33"}`. Returns the price, quantity and expiry. |
| `POST /purchases` | Takes `{"quote_id":"..."}`. Confirms the owned quote and returns its receipt. |
| `GET /holdings` | Returns total grams, total INR paid and count of settled purchases for the caller, including SIP instalments. |
| `GET /ledger` | Lists the caller's purchases and instalments, newest first. Supports `limit` and `offset`. |
| `POST /sips` | Takes `amount`, `frequency` and an ISO `start` date. Monthly plans can include `anchor_day`. |
| `GET /sips` | Lists the caller's plans, with state and next due date. Supports `limit` and `offset`. |
| `POST /sips/{id}/pause` or `/cancel` | Stops future instalments. A paused SIP can subsequently be cancelled. |
| `GET /events` | Reads the caller's durable audit log. Pass the last sequence as `after` to page forward. |
| `GET /health` | Checks SQLite access. |

Every POST requires an idempotency key. Reuse it when retrying a logical command. Identical retries return the saved response. Reusing the key with another payload returns 409. Reconfirming a consumed quote returns its existing receipt even with a new key. A fresh key on an explicit SIP creation denotes a new plan.

## Prices and schedules

* Amounts run from ₹10.00 through ₹50,000.00. Send decimal strings. The price feed is a replaceable local JSON file, `fixtures/price.json` by default or `GOLD_PRICE_FILE` in the process environment. Its price is a demo fixture. The bundled fixture models a ₹1 platform fee, 18% tax on that fee and 3% on the gold value. This is a simulation assumption chosen to reproduce the observed ₹10 checkout: ₹8.56 gold, ₹0.44 total GST, ₹1 fee, and 0.0006 g. The published ₹500 example uses a zero platform fee and shows ₹485.44 gold and ₹14.56 GST. Both profiles have regression tests. [Simplify Money gold checkout](https://www.simplifymoney.in/digital-gold.html)
* The database stores integer paise and ten-thousandths of a gram. Gold rounds down once. For a rate-only fixture without fees or tax, at ₹6,000.00/g, ₹333.33 buys 0.0555 g. A locked quote survives a later price outage until expiry. A new quote fails with 503 when the feed is missing or malformed.
* The scheduler checks every 15 seconds and handles up to 100 overdue instalments per pass. Each uses the price available when it executes. A feed outage leaves its due date pending. The worker retries on the next pass. The due-date advance, ledger entry and audit event commit together.
* Daily, weekly and monthly dates follow India time. A monthly plan anchored to the 31st uses the last day of a short month, then returns to the 31st. A SIP conversation remembers the caller's partially entered terms for five minutes. “Start a ₹100 gold SIP” followed by “every Friday” produces a dated weekly preview. An explicit past start asks for a replacement date. Pausing preserves history. Cancellation is terminal.
* Operator commands `python -m gold tick` and `python -m gold trace USER` run locally against `GOLD_DB` (default `data/gold.sqlite3`). Trace output is ordered JSON Lines with conversation intents and replies, quotes, receipts, retries, failures and instalment dates. Raw chat inputs, bearer tokens and provider credentials are omitted from the event log.

## Security checks

The source checker looks for dynamic SQL, unsafe Python calls and embedded Groq credentials. Run `python scripts/check_source.py --watch` to repeat it on source changes. This checkout also runs the check before each commit. Enable the same hook in another clone with `git config core.hooksPath .githooks`.

GitHub Actions has independent test and audit jobs for pushes, pull requests and a weekly schedule. The audit job runs Bandit and checks the resolved runtime dependencies against published advisories with pip-audit. To run the same checks locally:

```sh
.venv/bin/python -m pip install bandit pip-audit
.venv/bin/bandit -r gold -ll
.venv/bin/pip-audit -r requirements.txt
```

See [engineering decisions](DECISIONS.md) and [AI use, verification and delivery limits](DELIVERY.md).
