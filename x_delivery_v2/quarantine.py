"""Reviewed ambiguous transmissions. This registry never authorizes a resend."""
from __future__ import annotations
import hashlib

REVIEWED = {
    "result:20261012:23:9": {
        "owner": "8051b3dd36204b90931313b99f519fcf",
        "parent_post_id": "2109484570999763085",
        "content_sha256": "44ea47c25a121faa64c601e4113170950b120e821d668926d07f674007acc8b6",
        "claimed_at": "2026-10-12T12:45:22.410696+09:00",
        "reviewed_at": "2026-10-13T11:17:00+09:00",
        "reason": "X HTTP503 at 2026-10-12T03:45:25Z; Render returned HTTP502. No acknowledged result post ID. Outcome unknown.",
        "evidence": "docs/X_UNCERTAIN_20261013.json",
        "automatic_resend_prohibited": True,
    }
}


def classify(state, rkey):
    reviewed = REVIEWED.get(rkey)
    if not reviewed:
        return None
    receipt = (state.get("x_v2_receipts") or {}).get(rkey) or {}
    if receipt.get("status") == "sent" and str(receipt.get("post_id", "")).isdigit():
        return None
    if not receipt:
        raise ValueError("Reviewed ambiguous X receipt disappeared; resend remains forbidden")
    for field in ("owner", "parent_post_id", "content_sha256", "claimed_at"):
        if receipt.get(field) != reviewed[field]:
            raise ValueError("Reviewed ambiguous X receipt changed; no automatic reconciliation")
    payload = (receipt.get("row") or {}).get("post", "")
    if hashlib.sha256(payload.encode()).hexdigest() != receipt["content_sha256"]:
        raise ValueError("Quarantined X payload no longer matches its content hash")
    return {"key": rkey, "status": "quarantined", "underlying_status": receipt["status"],
            "reason": reviewed["reason"], "evidence": reviewed["evidence"],
            "automatic_resend_prohibited": True}
