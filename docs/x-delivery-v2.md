# X Delivery V2

The X production dispatcher reuses the existing PT1/PT2/Yuuki predictions,
featured-race selection gates, exact-ticket formatter, Render API and X account.
Discord predictions, Sokuhou, channels and AI engines are not replaced.

`x-delivery-v2-production.yml` performs a bounded pass. Existing X prediction and
result cron workflows also invoke the same dispatcher and share one concurrency
group without cancelling active sends. Discord's existing continuation wakes the
X dispatcher after two minutes of inactivity, so delayed cron events are not the
only opportunity to send. A GitHub-wide outage can still interrupt these runs.

Prediction eligibility remains 11–40 minutes before deadline, with fresh source
records and at most ten featured races per JST day. The Render API independently
rejects anything inside the ten-minute cutoff. Late predictions are skipped,
never back-posted. Selection rules, odds criteria and ticket plans are unchanged.

Archive payloads and compare-and-swap claims precede every X request. Numeric X
post IDs are required before a native receipt and the legacy posted-ID set are
updated. Uncertain/ambiguous requests remain held across restarts. Definite
retryable failures have a maximum of three attempts. Pending official results
can be checked again without exhausting this network-error retry budget.

Results are checked for the current and previous JST day only when the prediction
has a numeric posted ID. Existing result formatting and the existing Render reply
policy remain in use. Receipts record the original prediction parent ID.

All native receipts stay in `x-delivery-state` under
`data/x_post_delivery/YYYYMMDD.json` -> `x_v2_receipts`. The delivery audit lives at
`data/x_delivery_v2/YYYYMMDD/dispatcher.json` on that branch. It includes selection
skip reasons, held attempts and exact archive/ID matching plus a restart guard
verification that does not send another request. Receipt recovery artifacts are
retained if persistence fails after the X API acknowledged the post.

An idle successful run means no current candidate, not a successful X post.
Production proof requires a native sent receipt, actual numeric ID, source commit
and record digests, matching archive and posted-ID set, cutoff compliance, and
`production_verification` with both verification flags true. Never use a canary
or an expired historical prediction to claim a live delivery.
