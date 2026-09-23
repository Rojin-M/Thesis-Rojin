"""Dossier exports contain recorded evidence only, with no generated claims."""
import json
import re
from html import escape

from .protocol import utc_now


def dossier(store, candidate_id):
    return {"export_schema": 1, "exported_at": utc_now(), "candidate": store.get_candidate(candidate_id)}


def markdown_report(document):
    c = document["candidate"]
    # JSON fences preserve untrusted text as literal evidence. Escape backticks
    # in narrative cells; use a long fence for the full machine-readable record.
    def literal(value):
        return escape(str(value)).replace("`", "'").replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    eph = c["ephemeris"]
    lines = ["# Local research candidate dossier", "", f"Exported: {document['exported_at']}", "",
             f"- Candidate: {literal(c['id'])}", f"- Target: {literal(c['target_id'])} ({c['mission']})",
             f"- Cohort: **{c['cohort']}**", f"- Review: **{c['review_status']}** (revision {c['revision']})",
             f"- Execution: {c['job']['status']}; evidence: {c['evidence_state']}",
             f"- Period: {eph['period_days']} days; duration: {eph['duration_hours']} hours",
             f"- Epoch: {eph['epoch_bjd_tdb']} BJD TDB (input {eph['epoch_original']} {eph['epoch_system']})", ""]
    lines.extend("> " + warning for warning in c["warnings"])
    latest = {e["kind"]: e for e in c["evidence"]}
    model = latest.get("model_score", {})
    registry = latest.get("registry", {})
    diagnostic = latest.get("transit_diagnostics", {}).get("payload", {})
    coverage = diagnostic.get("event_coverage", diagnostic)
    lines.extend(["", "## Evidence for the reviewer", ""])
    if model.get("state") == "complete":
        score = model["payload"]
        lines.extend([f"- CNN ranking score: **{score['score']:.6f}**; logit {score.get('logit')}. Uncalibrated; uncertainty not estimated.",
                      f"- Model: {literal(score.get('model_name'))}; checkpoint `{score['model_sha256']}`.",
                      f"- Frozen Kepler TRAIN normalizer: `{score['normalization_sha256']}`.",
                      f"- Source validation threshold: {score.get('validation_threshold')} (context only; never a search rejection gate)."])
    else:
        lines.append("- CNN score unavailable. The proposal remains in the human review queue.")
    rp = registry.get("payload", {})
    comparison = latest.get("model_comparison", {})
    if comparison.get("state") == "complete":
        p = comparison["payload"]
        lines.extend(["", "### Experimental model comparison", "",
                      "Same saved blind-search input; reference score retained. These are uncalibrated ranking values, not planet probabilities.", "",
                      "| Training arm | Mean score | Seed range |", "| --- | ---: | ---: |"])
        for arm, row in p["by_arm"].items():
            lines.append(f"| {literal(arm)} | {row['mean_score']:.6f} | {row['min_score']:.6f}–{row['max_score']:.6f} |")
        lines.extend(["", f"Experiment: {literal(p['run_id'])}; specification `{p['spec_sha256']}`.",
                      "Seed ranges are not probability confidence intervals.", ""])
    lines.extend([f"- Registry snapshot: **{literal(rp.get('status', 'NOT_RUN'))}**; evidence {registry.get('state', 'not_run')}; as of {literal(rp.get('generated_at_utc', 'not recorded'))}.",
                  f"- Registry interpretation: {literal(rp.get('summary', 'No catalog assessment recorded.'))}",
                  f"- Covered events: {coverage.get('n_covered_events', 'not measured')} / {coverage.get('n_expected_events', 'not measured')} expected; odd/even white-noise difference {coverage.get('odd_even_difference_sigma', 'not measured')} sigma."])
    secondary = diagnostic.get("secondary_scan", {}).get("best")
    if secondary:
        lines.append(f"- Strongest scanned secondary: phase {secondary['phase']:.4f}, depth {secondary['depth']:.6g}, white-noise S/N {secondary['snr']:.3f}. No trials/red-noise calibration.")
    for kind in ("centroid", "contamination"):
        payload = latest.get(kind, {}).get("payload", {})
        for product in payload.get("products", []):
            if kind == "contamination":
                lines.append(f"- Pipeline aperture fractions: {literal(product.get('header_fractions', {}))}; nearby-source and aperture-dependence checks incomplete.")
            else:
                for axis, data in product.get("axes", {}).items():
                    lines.append(f"- {axis} event centroid shift: {data.get('shift_pixel')} pixels, white-noise error {data.get('white_error_pixel')}; difference-image localization incomplete.")
    lines.extend(["", "### Review attention", "", ", ".join(c.get("review_triage", {}).get("flags", [])) or "No automated attention flags recorded.",
                  "", "Every signal can be reviewed or placed on hold, including low scores, incomplete inputs, aliases and unusual morphology. No automatic planet confirmation or rejection is performed."])
    lines.extend(["", "## Incomplete evidence", "", ", ".join(c["incomplete_evidence"]) or "All required evidence is recorded; this does not establish scientific validity.",
                  "", "## Evidence", "", "| Kind | State | Recorded summary |", "| --- | --- | --- |"])
    lines.extend(f"| {e['kind']} | {e['state']} | {literal(e['summary'])} |" for e in c["evidence"])
    lines.extend(["", "## Artifact receipts", ""])
    lines.extend(f"- [{literal(a['filename'])}](/api/artifacts/{a['id']}): `{a['sha256']}` ({a['size_bytes']} bytes)" for a in c["artifacts"])
    text = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
    fence = "`" * (max((len(part) for part in re.findall(r"`+", text)), default=0) + 4)
    lines.extend(["", "## Complete persisted record", "", fence + "json", text, fence, ""])
    return "\n".join(lines)
