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
    if score.get("payload", {}).get("score_role") == "fallback":
        flags.append("supermodel_unavailable_reference_fallback")
    multiple = "supermodel_v2" in evidence or "model_comparison" in evidence
    return {"flags": sorted(set(flags)), "automatic_rejection": False, "human_review_required": True,
            "calibrated_uncertainty": "unavailable", "model_disagreement": "inspect_recorded_expert_scores" if multiple else "single_model_only_comparator_disagreement_not_yet_available",
            "policy": "Every proposal remains addressable and reviewable irrespective of score, gaps or unusual morphology"}


def compact_assessment(evidence, *, mission=None, cohort=None):
    from .probabilities import probability_assessment
    latest = {e["kind"]: e for e in evidence}
    model = latest.get("model_score", {})
    registry = latest.get("registry", {})
    payload = model.get("payload", {})
    probability = probability_assessment(model, mission=mission, cohort=cohort)
    if payload.get("model_name") == "crossfit_nonlinear_supermodel_v2":
        probability["benchmark"]["reason"] = ("V2 already uses its frozen benchmark temperature for ranking. "
            "The separate reference-CNN calibrator does not apply; a validated blind-search planet probability is unavailable.")
    return {"score": payload.get("score") if model.get("state") == "complete" else None,
            "model_name": payload.get("model_name"), "score_role": payload.get("score_role", "reference"),
            "fallback_reason": payload.get("fallback_reason"),
            "score_state": model.get("state", "not_run"), "registry_status": registry.get("payload", {}).get("status") or "NOT_RUN",
            "registry_state": registry.get("state", "not_run"), "confirmation_probability": False,
            "probability": probability}
