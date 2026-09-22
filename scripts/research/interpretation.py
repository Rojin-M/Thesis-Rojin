"""Pure, current evidence summaries shared by HTTP, reports and workers."""


def review_flags(candidate):
    evidence = {e["kind"]: e for e in candidate["evidence"]}
    flags = []
    score = evidence.get("model_score", {})
    if score.get("state") != "complete":
        flags.append("model_score_missing_review_retained")
    else:
        p = score["payload"]
        if p.get("validation_threshold") is not None and p["score"] < p["validation_threshold"]:
            flags.append("below_source_validation_threshold_review_retained")
            registry = evidence.get("registry", {}).get("payload", {})
            if any(m.get("ephemeris_match") == "DIRECT" and m.get("source_current") for m in registry.get("matches", [])):
                flags.append("catalog_and_model_disagreement")
    diagnostics = evidence.get("transit_diagnostics", {}).get("payload", {})
    flags.extend(diagnostics.get("event_coverage", diagnostics).get("warnings", []))
    flags.extend("missing_" + kind for kind in candidate["incomplete_evidence"])
    return {"flags": sorted(set(flags)), "automatic_rejection": False, "human_review_required": True,
            "calibrated_uncertainty": "unavailable", "model_disagreement": "single_model_only_comparator_disagreement_not_yet_available",
            "policy": "Every proposal remains addressable and reviewable irrespective of score, gaps or unusual morphology"}


def compact_assessment(evidence):
    latest = {e["kind"]: e for e in evidence}
    model = latest.get("model_score", {})
    registry = latest.get("registry", {})
    return {"score": model.get("payload", {}).get("score") if model.get("state") == "complete" else None,
            "score_state": model.get("state", "not_run"), "registry_status": registry.get("payload", {}).get("status", "NOT_RUN"),
            "registry_state": registry.get("state", "not_run"), "confirmation_probability": False}
