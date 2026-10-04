# Discord Delivery V2: production rollout

Existing prediction builders, channel routing, notification policy, X and
independent Sokuhou delivery remain in place. Current workflows remain enabled.

## First production stream

The existing Yuuki workflow and the short production dispatcher both call the
same `deliver_once` guard on `discord-delivery-state`. They may discover the same
race; only the successful atomic claimant can POST. A sent receipt must contain
a numeric Discord message ID. Old receipts without an ID are held as
`legacy_unverified`, never replayed and never counted as verified successes.

Deployment begins with the new dispatcher in audit mode. Enable
`DISCORD_DELIVERY_V2_STREAMS: 'yuuki,yuuki_selected'` only after branch validation,
canary acknowledgement and the existing Yuuki workflow's shared guard are verified.
The existing workflow's watcher is retained during this first overlap.
The deployed dispatcher now overlaps Yuuki production after its new silent
canary returned message ID `1556270803773948022` with a durable state receipt.
No next-race proof was available after the final 2026-10-04 closing time, 20:45 JST.
Main and other streams remain on their current production paths.

## Catch-up and missed races

Each wake-up discovers the current day's venues and closing times. It scans all
currently eligible, unexpired races, even if the previous checkpoint is missing
or hours old. Stored predictions use the original engine, formatter and digest.
The guard checks the real time again after its durable claim and before POST.
It never sends expired predictions. Watchdog results, schedules and the last
successful check are persisted in the dedicated state branch. Selected streams
are expected only when an existing prediction passes the existing selection gate;
`sniper_skip` is not a sent longshot.

GitHub cron remains a wake-up signal without a timing guarantee. A race whose
entire eligible window elapses while no process runs cannot be recovered as a
prediction. It is recorded as missed. An independent wake-up source is required
to protect against hours-long absence of all scheduled runs.

## Recovery and retries

An acknowledged prediction and its exact original record are committed to the
state branch before the legacy report mirror is marked delivered. Local mirror
loss restores that same record and message ID without another POST. Recovery
artifacts also preserve acknowledgements if a subsequent state write fails.
The new dispatcher does not publish mutable scoreboard snapshots to main;
the existing Yuuki workflow remains their publisher. Critical prediction and
delivery mirrors persist separately from derived scoreboards, whose conflicts
remain available in recovery artifacts without failing prediction delivery.

Only a definite HTTP 429 schedules another attempt, up to three attempts with
the immutable original content and Discord's retry-after delay. Timeouts or an
invalid acknowledgement are uncertain and held. HTTP failures and uncertain
sends raise workflow errors and use the existing report webhook for a deduplicated
incident notice. No blind retry is permitted.

## Later streams

Main, selected, mid-odds, mid-odds-selected and longshot have opt-in transport
bridges; they are not enabled in the first dispatcher rollout. Enabling another
producer requires routing its existing sender through the same durable guard
before enabling live dispatcher production for it. Verify exact picks, deadline,
message ID, state receipt, restart deduplication, report reflection and delayed
wake-up behavior before progressing. Sokuhou retains its independent receipt
branch and acknowledgement path. Hiyori, PT1/2 and X retain their current paths.

## Verification

`python -m unittest discover -s tests -p 'test_delivery_v2*.py' -v`

The suite includes a delayed 18:00 -> 18:12 wake-up, multiple remaining targets,
past-deadline exclusion, simultaneous claims, loss of both legacy prediction and
receipt files, failed persistence after acknowledgement, uncertain sends, bounded
429 retries, and persisted missed records. Green Actions alone are insufficient:
production recovery requires actual numeric message IDs and durable receipts.

Unit tests keep both receipt and acknowledgement recovery files in temporary
directories. Numeric IDs returned by mocked senders are fixtures, never production
proof. Early validation artifacts may contain the historical `hello` fixture with
ID `987654321`; it must not be used to reconstruct any actual Discord delivery.
