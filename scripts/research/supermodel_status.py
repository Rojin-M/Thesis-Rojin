"""Lightweight deployment visibility; HTTP processes never load model weights."""
import json
from datetime import datetime, timezone


def deployment_status(store):
    path = store.path.parent / "supermodel/service.json"
    state = {"state": "not_started", "mode": None, "heartbeat_at": None}
    try:
        if path.exists():
            if path.stat().st_size > 1024**2:
                raise ValueError("Oversized supermodel service state")
            state = json.loads(path.read_text())
            if state.get("state") in ("starting", "running"):
                heartbeat = datetime.fromisoformat(state["heartbeat_at"].replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - heartbeat).total_seconds() > 120:
                    state["state"] = "stale"
    except (OSError, ValueError, KeyError, TypeError):
        state = {"state": "unavailable", "mode": None, "error": "Service state cannot be verified"}
    with store.connection() as db:
        counts = {row[0] or "reference": row[1] for row in db.execute(
            "SELECT json_extract(e.payload_json,'$.score_role'),COUNT(*) FROM evidence e "
            "WHERE e.kind='model_score' AND e.state='complete' AND e.rowid=(SELECT MAX(s.rowid) "
            "FROM evidence s WHERE s.candidate_id=e.candidate_id AND s.kind='model_score') "
            "GROUP BY json_extract(e.payload_json,'$.score_role')")}
        shadows = {row[0]: row[1] for row in db.execute(
            "SELECT e.state,COUNT(*) FROM evidence e WHERE e.kind='supermodel_v2' "
            "AND e.rowid=(SELECT MAX(s.rowid) FROM evidence s WHERE s.candidate_id=e.candidate_id "
            "AND s.kind='supermodel_v2') GROUP BY e.state")}
    return {**state, "score_counts": counts, "shadow_counts": shadows,
            "policy": "v2_primary_when_all_eleven_experts_available_else_reference_CNN",
            "planet_probability": False, "automatic_rejection": False}
