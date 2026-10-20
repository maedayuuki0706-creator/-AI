# Independent fusion prospective research state

This separate Git branch is **not main**, not production, and not the existing
`research-venue-specialists-state`. It contains no verified fusion forecasts
at initialization.

Expected immutable data layout:

- `data/venue_fusion_forward_v1/forecasts/YYYYMMDD/YYYYMMDD_JCD_RNO.json`:
  generated and locally frozen from original official pre-deadline pages,
  with three model cards (10 unique trifecta tickets each)
- `data/venue_fusion_forward_v1/receipts/YYYYMMDD/YYYYMMDD_JCD_RNO.json`:
  separately committed ONLY after the forecast blob is pushed and read
  back from Git before the race deadline minus 3 minutes

The receipt carries the original forecast digest, official source hash,
first Git commit SHA and runner-clock observation. The receipt itself must
also be pushed and read back before the cutoff. An error, race already
present, mismatch, or late delivery is **excluded**, not patched/replayed.

Independent post-race grading is not written here by default and must verify
both frozen Git commits and the official result, including excluded refunds.

**Current status at creation: no live prediction, no remotely received race.**
The production Discord, X, main models, Sheets, existing four-venue
research worker and its state branch are unchanged. There is no recurring
new publisher; a separate reviewed opt-in live workflow is still needed.

WARNING: The research runner's clock and Git committer timestamp are NOT
a cryptographic independent GitHub server-time attestation. Never promise
that their presence alone proves race outcome could not have been known.
