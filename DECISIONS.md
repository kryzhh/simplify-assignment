# Decision log

1. **Return the buy card as data.** In the observed app, asking for the missing button produced more text about the button. Here the card includes the actual confirmation path and payload. Reopening it retrieves the same unexpired quote. A text-only instruction would recreate the failure.
2. **Use an explicit confirmation.** A question such as “How much gold can I buy for ₹500?” and a purchase instruction can contain the same nouns and numbers. Both may produce a quote. Only the confirmation endpoint can book a purchase. Groq has no payment tool.
3. **Keep pricing simple and visible.** The app's ₹10 quote showed fees and GST, but one receipt doesn't establish its fee schedule. The bundled pricing fixture matches the observed ₹10 screen. Fee and tax assumptions live in the price feed. Each quote locks its breakdown and its weight, so changing the feed later cannot change the receipt. Integer division rounds the resulting gold weight down to four places. Rounding to nearest could allocate more gold than the amount buys.
4. **Give retries two independent protections.** A user-scoped key identifies a command and binds its payload. A unique quote ID in the ledger also catches a confirmation resent with a different key. Deduplicating by amount would suppress legitimate repeat purchases.
5. **Use SQLite for the single-host service.** A single transaction covers receipts, request replay and audit events. A queue and a second database would introduce a crash boundary between booking and acknowledgement. WAL allows reads during short writes. The external classification call happens outside the write transaction.
6. **Keep the requested monthly day.** Advancing one month from February 28 would move a January 31 plan to March 28. Store the original anchor and clamp only the individual due date. An explicit start in the past gets a validation error before any instalment can become due.
7. **Promise a short-lived quote.** Honour a previously issued quote for five minutes if the source fails. New quotes fail and SIP instalments wait. Falling back silently to a prior market price would make two purchases look equivalent when they used different pricing policies.
8. **Constrain the LLM to intent classification.** The server validates amounts, dates and ownership and writes the final actionable response. This keeps English and Hinglish routing extensible while preserving deterministic checkout. A local router handles timeouts, provider limits and offline review.
9. **Write an audit event in the ledger transaction.** A console message emitted before commit can describe a purchase that later rolls back. An event in the same commit can be exported by user even after a restart. Message intent and structured results are sufficient to follow the business events without preserving the raw chat transcript.
10. **Provision identities outside the API.** A local operator issues random tokens bound to one pseudonymous user. A caller-supplied user header would make another user's receipts guessable. Only the token digest is stored. An internet-facing deployment would need a managed identity lifecycle.

## How the example messages behave

| Input | Response and reason |
| --- | --- |
| Investment timing, “safest thing”, or “bhai sona lena chahiye ya nahi abhi?” | Discuss price risk and ask about the user's horizon. A universal buy recommendation would require context the user hasn't given. |
| Gold versus an FD | Explain the difference between market value and an agreed rate and term. Ask when the money is needed. |
| “gold” or “I want to invest 5000” | Ask what they want to learn or what asset and purchase type they mean. An amount alone gives no authority to buy. |
| “How much gold can I buy for 500 rupees?” | Calculate quantity from the configured rate and offer a five-minute confirmation card. |
| “1000 ka gold le lo mere liye” or a ₹333.33 buy request | Parse the rupee amount exactly and display the same confirmation card as the English purchase flow. |
| ITR deadline or cab booking | Refer the tax question to the official filing portal or explain the service's scope for unrelated requests. |
| Free gold, instruction override, or system prompt request | Return the purchase requirements or scope. The model has no ledger access and checkout requires authentication and an owned quote. |
| Negative, ₹0.50 or ₹100,000,000,000 | Return the valid range or format and create no quote. A fraction of a rupee is valid precision but below the chosen minimum. |
| ₹100 daily or ₹500 monthly from the 31st | Preview the frequency, first date and amount. Return a SIP creation action requiring confirmation. Preserve the monthly anchor. |
| Weekly starting yesterday | Ask for today or a future date. A new plan must not create retroactive instalments. |
| “Pause my SIP” | Offer a confirmation if exactly one eligible plan exists. With several plans, ask the user to select from their list. |
| Repeat a purchase, SIP creation, or instalment run | Replay a command key, reuse a consumed quote's receipt, or use the plan and due-date uniqueness constraint, respectively. |

## Additional product scenarios

These cases are engineering predictions about likely variations on the assignment. The public product describes purchases, gifting, recurring plans and holdings queries. It also describes spending analysis using linked accounts. [Digital gold](https://www.simplifymoney.in/digital-gold.html) · [Kuber.AI in Simplify Money](https://www.simplifymoney.in/)

| Scenario | Expected behavior |
| --- | --- |
| Ask how much gold you own after previewing and confirming different orders | Total only settled ledger entries belonging to the caller. Ignore outstanding quotes. |
| Ask to sell, gift gold, buy a mutual fund SIP, or summarize food expenses | Explain the applicable product boundary. Return no actionable gold purchase or invented expense total. |
| Withdraw a pending purchase, then tap its saved confirmation card | Reject the withdrawn quote. Preserve completed receipts. |
| Start a SIP, then reply “every Friday” | Recover that user's unexpired draft and show the weekly start date in India time. Another user's reply starts with an empty draft. |
| Enter Devanagari digits, an INR amount next to “24K”, or a malformed decimal | Normalize currency and purity notation. Ask for a valid rupee amount when parsing is ambiguous. |
