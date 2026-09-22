"""Explicit synthetic UI fixture. Never imported into the live store by startup."""
import math

from .protocol import STAGES, digest, utc_now
from .provenance import register_code


def seed_fixture(store, artifacts, protocol_id):
    with store.connection() as db:
        old = db.execute("SELECT id FROM jobs WHERE job_key='synthetic-ui-fixture-v1'").fetchone()
    if old:
        job = store.get_job(old["id"])
        code_id = job["code_provenance_id"]
        if job["protocol_id"] != protocol_id:
            raise ValueError("Fixture exists under a different protocol")
    else:
        code_id = register_code(store)["id"]
    source = store.register_provenance(kind="fixture", identity="synthetic-ui-fixture-v1",
                                       sha256_digest=digest({"generator": "analytic_box", "version": 1}),
                                       retrieved_at="2000-01-01T00:00:00Z",
                                       details={"synthetic": True, "purpose": "UI and persistence demonstration; no science result"})
    job = store.create_job(job_key="synthetic-ui-fixture-v1", cohort="synthetic_fixture", protocol_id=protocol_id,
                           code_provenance_id=code_id, inputs={"synthetic": True, "generator": "analytic_box_v1"})
    for stage in STAGES[:3]:
        current = next(s for s in store.get_job(job["id"])["stages"] if s["name"] == stage)
        if current["status"] == "queued":
            store.skip_stage(job["id"], stage, actor="fixture-generator", reason="Synthetic data; no public retrieval or target selection")
    claim = store.claim_stage(job["id"], "detection", worker="fixture-generator")
    if claim:
        store.finish_stage(claim["lease_token"], result={"synthetic": True, "method": "analytic fixture, no blind search"})
    candidate = store.put_candidate(job_id=job["id"], signal_key="fixture-box-1", target_id="SYNTHETIC-001", mission="TESS",
                                    period_days=3., epoch=1500., epoch_system="BTJD", duration_hours=3.,
                                    detection={"method": "analytic_box_fixture", "ephemeris_origin": "synthetic_fixture"},
                                    provenance_id=source["id"])
    x = [1500. + i / 100. for i in range(901)]
    phase = [((t - 1500. + 1.5) % 3. - 1.5) / 3. for t in x]
    y = [1. - (0.01 if abs(p) < 3. / 24. / 3. / 2. else 0.) + .0005 * math.sin(i * 2.31)
         for i, p in enumerate(phase)]
    for key, axis, title, label, kind in (("unfolded", x, "SYNTHETIC fixture · unfolded light curve", "Time (BTJD, TDB days)", "time_series"),
                                          ("folded", phase, "SYNTHETIC fixture · folded at assigned period", "Phase (cycles)", "phase_folded")):
        artifacts.put_plot({"kind": kind, "title": title, "x_label": label, "y_label": "Relative flux",
                            "time_system": "BTJD", "x": axis, "y": y, "synthetic": True},
                           candidate_id=candidate["id"], artifact_key=key, filename=key + ".json",
                           metadata={"synthetic": True, "full_points": len(x), "preview_points": len(x)})
    store.put_evidence(candidate_id=candidate["id"], evidence_key="fixture-lightcurve-v1", kind="lightcurve",
                       state="complete", summary="Analytic synthetic box transit for testing the interface only.",
                       payload={"synthetic": True, "samples": len(x)}, provenance_id=source["id"])
    store.put_evidence(candidate_id=candidate["id"], evidence_key="fixture-registry-v1", kind="registry",
                       state="not_run", summary="Synthetic target; public catalogs were not queried.")
    current = next(s for s in store.get_job(job["id"])["stages"] if s["name"] == "features")
    if current["status"] == "queued":
        claim = store.claim_stage(job["id"], "features", worker="fixture-generator")
        store.finish_stage(claim["lease_token"], error={"code": "synthetic_failure", "retryable": False,
                           "message": "Deliberate fixture failure to demonstrate an incomplete pipeline; no model was run."})
    return store.get_candidate(candidate["id"])
