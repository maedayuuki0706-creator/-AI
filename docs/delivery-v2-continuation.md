# Discord Delivery V2 continuation

The production dispatcher preserves its cron and all existing prediction engines,
webhooks and delivery workflows. After a validated short run, it requests the next
production run using `workflow_dispatch` and the existing `GITHUB_TOKEN` with
`actions: write`. This avoids waiting for another delayed `schedule` event.

The continuation checks for an already queued run before requesting another.
Existing Main, Yuuki, Sokuhou, Hiyori and PT1/2 workflows are woken only when they
are active, have no unfinished run, and have not started in the last five minutes.
It never cancels a run, enables a disabled workflow or posts a test prediction.
Prediction duplicate prevention still uses the shared durable receipts.

Within the 150-second generation budget, pending exhibition and data checks are
revisited every 20 seconds, with at most four races processed concurrently. A
race whose deadline has passed is never sent. A missing race detected after its
deadline remains `missed`; continuation runs proceed even if this makes the
dispatcher report `degraded`.

Checkpoint fields `trigger_event`, `workflow_run_id` and `wake_reason` identify
the actual wake-up origin. A continuation is `workflow_dispatch`, not evidence
that the GitHub cron fired. Native numeric message IDs and matching records are
still required for production verification.

Set the repository variable `DISCORD_DELIVERY_V2_CONTINUATION_ENABLED` to `0`
to stop only the added continuation. Existing cron and workflows remain intact.
The next manual, push or schedule run can bootstrap continuation again when the
variable is enabled. A repository-wide Actions/API outage can still interrupt
this chain; this change removes cron dependence, not dependence on GitHub.
