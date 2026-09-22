"""SQLite research records with immutable inputs and fenced, restartable stages.

Every operation uses a fresh connection and short transaction. A worker may run
outside the transaction, but must present its live lease token before publishing
results. No transaction is held while downloading, plotting or running a model.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .protocol import (ARTIFACT_MEDIA_TYPES, COHORTS, EVIDENCE_STATES, REVIEW_STATUSES, ConflictError,
                       NotFoundError, ValidationError, canonical_json, digest,
                       ephemeris, finite_number, identifier, nonempty, sha256,
                       timestamp, utc_now, validate_protocol)
from .interpretation import compact_assessment, review_flags

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS protocols (
    id TEXT PRIMARY KEY, document_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance (
    id TEXT PRIMARY KEY, document_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY, mission TEXT NOT NULL, release_key TEXT NOT NULL,
    available_at TEXT NOT NULL, provenance_id TEXT NOT NULL REFERENCES provenance(id),
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(mission, release_key));
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY, release_id TEXT NOT NULL REFERENCES releases(id),
    product_key TEXT NOT NULL, target_id TEXT NOT NULL, source_uri TEXT NOT NULL,
    metadata_json TEXT NOT NULL, provenance_id TEXT NOT NULL REFERENCES provenance(id),
    created_at TEXT NOT NULL, UNIQUE(release_id, product_key));
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, job_key TEXT NOT NULL UNIQUE, cohort TEXT NOT NULL,
    protocol_id TEXT NOT NULL REFERENCES protocols(id),
    code_provenance_id TEXT NOT NULL REFERENCES provenance(id),
    release_id TEXT REFERENCES releases(id), product_id TEXT REFERENCES products(id),
    inputs_json TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stages (
    job_id TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL, position INTEGER NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
    lease_token TEXT, lease_until TEXT, worker TEXT, result_json TEXT, error_json TEXT,
    updated_at TEXT NOT NULL, PRIMARY KEY(job_id, name), UNIQUE(job_id, position));
CREATE TABLE IF NOT EXISTS attempts (
    token TEXT PRIMARY KEY, job_id TEXT NOT NULL, stage TEXT NOT NULL, number INTEGER NOT NULL,
    worker TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    error_json TEXT, result_json TEXT, FOREIGN KEY(job_id, stage) REFERENCES stages(job_id, name));
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), signal_key TEXT NOT NULL,
    target_id TEXT NOT NULL, mission TEXT NOT NULL, ephemeris_json TEXT NOT NULL,
    detection_json TEXT NOT NULL, provenance_id TEXT NOT NULL REFERENCES provenance(id),
    review_status TEXT NOT NULL DEFAULT 'unreviewed', revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(job_id, signal_key));
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id),
    evidence_key TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, summary TEXT NOT NULL,
    payload_json TEXT NOT NULL, provenance_id TEXT REFERENCES provenance(id),
    created_at TEXT NOT NULL, UNIQUE(candidate_id, evidence_key));
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id),
    artifact_key TEXT NOT NULL, kind TEXT NOT NULL, media_type TEXT NOT NULL,
    filename TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(candidate_id, artifact_key));
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT NOT NULL REFERENCES candidates(id),
    revision INTEGER NOT NULL, status TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(candidate_id, revision));
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT REFERENCES jobs(id),
    candidate_id TEXT REFERENCES candidates(id), kind TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS processing_runs (
    job_id TEXT NOT NULL REFERENCES jobs(id), worker_key TEXT NOT NULL,
    spec_json TEXT NOT NULL, provenance_id TEXT NOT NULL REFERENCES provenance(id),
    created_at TEXT NOT NULL, PRIMARY KEY(job_id,worker_key));
CREATE INDEX IF NOT EXISTS evidence_candidate ON evidence(candidate_id, kind);
CREATE INDEX IF NOT EXISTS candidates_job ON candidates(job_id);
CREATE INDEX IF NOT EXISTS events_job ON events(job_id, id);
CREATE INDEX IF NOT EXISTS stages_state ON stages(status, lease_until);
"""


def _decode(row):
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json"):
            value = result.pop(key)
            result[key[:-5]] = json.loads(value) if value is not None else None
    return result


def _one(db, query, params=()):
    row = db.execute(query, params).fetchone()
    if row is None:
        raise NotFoundError("Record not found")
    return _decode(row)


def _rows(db, query, params=()):
    return [_decode(row) for row in db.execute(query, params)]


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            # A read transaction gives dossier exports one consistent snapshot.
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Rollback journalling is intentional: this project may reside on a
        # shared filesystem, where WAL's shared-memory assumptions do not hold.
        with sqlite3.connect(str(self.path), timeout=10) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ConflictError(f"Unsupported database schema {version}")
            db.execute("PRAGMA journal_mode=DELETE")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")
        from .watcher_store import WatchStore
        WatchStore(self).initialize()
        return self

    @staticmethod
    def _event(db, kind, payload, job_id=None, candidate_id=None):
        db.execute("INSERT INTO events(job_id,candidate_id,kind,payload_json,created_at) VALUES(?,?,?,?,?)",
                   (job_id, candidate_id, kind, canonical_json(payload), utc_now()))

    @staticmethod
    def _immutable(db, table, key_columns, fields):
        # Table/column names come only from internal constants, never HTTP data.
        where = " AND ".join(f"{key}=?" for key in key_columns)
        row = db.execute(f"SELECT * FROM {table} WHERE {where}", tuple(fields[k] for k in key_columns)).fetchone()
        if row is not None:
            if any(row[key] != value for key, value in fields.items() if key not in ("id", "created_at", "updated_at")):
                raise ConflictError(f"{table} identity already exists with different content")
            return _decode(row)
        keys = list(fields)
        db.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
                   tuple(fields[k] for k in keys))
        return _one(db, f"SELECT * FROM {table} WHERE {where}", tuple(fields[k] for k in key_columns))

    def register_protocol(self, document):
        document = validate_protocol(document)
        with self.connection(True) as db:
            return self._immutable(db, "protocols", ("id",), {
                "id": digest(document), "document_json": canonical_json(document), "created_at": utc_now()})

    def register_provenance(self, *, kind, identity, sha256_digest, retrieved_at, details=None):
        document = {"kind": identifier(kind, "provenance kind"), "identity": nonempty(identity, "identity", 2048),
                    "sha256": sha256(sha256_digest), "retrieved_at": timestamp(retrieved_at), "details": details or {}}
        with self.connection(True) as db:
            return self._immutable(db, "provenance", ("id",), {
                "id": digest(document), "document_json": canonical_json(document), "created_at": utc_now()})

    def get_provenance(self, provenance_id):
        with self.connection() as db:
            return _one(db, "SELECT * FROM provenance WHERE id=?", (provenance_id,))

    def freeze_processing_run(self, job_id, worker_key, spec):
        """Pin downstream source/model/settings once, atomically across restarts."""
        identifier(worker_key, "worker_key")
        with self.connection(True) as db:
            _one(db, "SELECT * FROM jobs WHERE id=?", (job_id,))
            old = db.execute("SELECT * FROM processing_runs WHERE job_id=? AND worker_key=?", (job_id, worker_key)).fetchone()
            if old is not None:
                row = _decode(old)
                if row["spec"] != spec:
                    raise ConflictError("Downstream code/model/settings changed; preserve this run and use a new versioned job")
                return row
            now = utc_now()
            document = {"kind": "processing_run", "identity": job_id + ":" + worker_key,
                        "sha256": digest(spec), "retrieved_at": now, "details": spec}
            provenance = self._immutable(db, "provenance", ("id",), {"id": digest(document),
                "document_json": canonical_json(document), "created_at": now})
            return self._immutable(db, "processing_runs", ("job_id", "worker_key"), {
                "job_id": job_id, "worker_key": worker_key, "spec_json": canonical_json(spec),
                "provenance_id": provenance["id"], "created_at": now})

    def get_protocol(self, protocol_id):
        with self.connection() as db:
            return _one(db, "SELECT * FROM protocols WHERE id=?", (protocol_id,))

    def register_release(self, *, mission, release_key, available_at, provenance_id, metadata=None):
        if mission not in ("TESS", "Kepler"):
            raise ValidationError("mission must be TESS or Kepler")
        if timestamp(available_at) > utc_now():
            raise ValidationError("Future scheduled availability is not an observed public release")
        fields = {"id": uuid.uuid4().hex, "mission": mission, "release_key": nonempty(release_key, "release_key"),
                  "available_at": timestamp(available_at), "provenance_id": provenance_id,
                  "metadata_json": canonical_json(metadata or {}), "created_at": utc_now()}
        with self.connection(True) as db:
            _one(db, "SELECT * FROM provenance WHERE id=?", (provenance_id,))
            return self._immutable(db, "releases", ("mission", "release_key"), fields)

    def register_product(self, *, release_id, product_key, target_id, source_uri, provenance_id, metadata=None):
        fields = {"id": uuid.uuid4().hex, "release_id": release_id,
                  "product_key": nonempty(product_key, "product_key", 512), "target_id": nonempty(target_id, "target_id"),
                  "source_uri": nonempty(source_uri, "source_uri", 2048), "provenance_id": provenance_id,
                  "metadata_json": canonical_json(metadata or {}), "created_at": utc_now()}
        with self.connection(True) as db:
            _one(db, "SELECT * FROM releases WHERE id=?", (release_id,))
            _one(db, "SELECT * FROM provenance WHERE id=?", (provenance_id,))
            return self._immutable(db, "products", ("release_id", "product_key"), fields)

    def create_job(self, *, job_key, cohort, protocol_id, code_provenance_id, inputs=None,
                   release_id=None, product_id=None):
        if cohort not in COHORTS:
            raise ValidationError("An explicit supported cohort is required")
        now = utc_now()
        fields = {"id": uuid.uuid4().hex, "job_key": nonempty(job_key, "job_key", 512), "cohort": cohort,
                  "protocol_id": protocol_id, "code_provenance_id": code_provenance_id,
                  "release_id": release_id, "product_id": product_id, "inputs_json": canonical_json(inputs or {}),
                  "status": "queued", "created_at": now, "updated_at": now}
        with self.connection(True) as db:
            protocol = _one(db, "SELECT * FROM protocols WHERE id=?", (protocol_id,))["document"]
            if cohort == "prospective_search" and not protocol["review"]["prospective_search_ready"]:
                raise ValidationError("This provisional protocol does not authorize prospective search")
            _one(db, "SELECT * FROM provenance WHERE id=?", (code_provenance_id,))
            if release_id:
                _one(db, "SELECT * FROM releases WHERE id=?", (release_id,))
            if product_id:
                product = _one(db, "SELECT * FROM products WHERE id=?", (product_id,))
                if product["release_id"] != release_id:
                    raise ValidationError("Job product and release do not agree")
            old = db.execute("SELECT * FROM jobs WHERE job_key=?", (job_key,)).fetchone()
            if old is not None:
                if any(old[k] != v for k, v in fields.items() if k not in ("id", "created_at", "updated_at", "status")):
                    raise ConflictError("Job key reused for different inputs; use a new versioned key")
                return _decode(old)
            job = self._immutable(db, "jobs", ("job_key",), fields)
            for position, name in enumerate(protocol["stages"]):
                db.execute("INSERT INTO stages(job_id,name,position,status,max_attempts,updated_at) VALUES(?,?,?,?,?,?)",
                           (job["id"], name, position, "queued", protocol["limits"]["stage_max_attempts"], now))
            self._event(db, "job_created", {"cohort": cohort}, job["id"])
            return job

    @staticmethod
    def _refresh_job(db, job_id):
        states = [row[0] for row in db.execute("SELECT status FROM stages WHERE job_id=?", (job_id,))]
        status = ("failed" if "failed" in states else "running" if "running" in states
                  else "succeeded" if all(s in ("succeeded", "skipped") for s in states) else "queued")
        db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, utc_now(), job_id))

    def _recover(self, db, now):
        expired = _rows(db, "SELECT * FROM stages WHERE status='running' AND lease_until<=?", (now,))
        for stage in expired:
            error = {"code": "lease_expired", "message": "Worker lease expired; outcome was not committed", "retryable": True}
            state = "queued" if stage["attempts"] < stage["max_attempts"] else "failed"
            db.execute("UPDATE attempts SET status='abandoned',finished_at=?,error_json=? WHERE token=?",
                       (now, canonical_json(error), stage["lease_token"]))
            db.execute("UPDATE stages SET status=?,lease_token=NULL,lease_until=NULL,worker=NULL,error_json=?,updated_at=? WHERE job_id=? AND name=?",
                       (state, canonical_json(error), now, stage["job_id"], stage["name"]))
            self._event(db, "lease_expired", {"stage": stage["name"], "attempt": stage["attempts"]}, stage["job_id"])
            self._refresh_job(db, stage["job_id"])
        return len(expired)

    def recover_expired(self):
        with self.connection(True) as db:
            return self._recover(db, utc_now())

    def claim_stage(self, job_id, stage_name, *, worker, lease_seconds=900):
        identifier(stage_name, "stage_name")
        nonempty(worker, "worker")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValidationError("lease_seconds must be an integer from 1 to 3600")
        now = utc_now()
        with self.connection(True) as db:
            self._recover(db, now)
            stage = _one(db, "SELECT * FROM stages WHERE job_id=? AND name=?", (job_id, stage_name))
            if stage["status"] == "succeeded" or stage["status"] == "skipped":
                return None
            if stage["status"] != "queued" or stage["attempts"] >= stage["max_attempts"]:
                raise ConflictError("Stage is not claimable; failed stages need an explicit retry")
            preceding = db.execute("SELECT 1 FROM stages WHERE job_id=? AND position<? AND status NOT IN ('succeeded','skipped')",
                                   (job_id, stage["position"])).fetchone()
            if preceding:
                raise ConflictError("Earlier stages are incomplete")
            token = uuid.uuid4().hex
            until = timestamp((datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat())
            db.execute("UPDATE stages SET status='running',attempts=attempts+1,lease_token=?,lease_until=?,worker=?,error_json=NULL,updated_at=? WHERE job_id=? AND name=?",
                       (token, until, worker, now, job_id, stage_name))
            db.execute("INSERT INTO attempts(token,job_id,stage,number,worker,status,started_at) VALUES(?,?,?,?,?,'running',?)",
                       (token, job_id, stage_name, stage["attempts"] + 1, worker, now))
            self._event(db, "stage_claimed", {"stage": stage_name, "attempt": stage["attempts"] + 1, "worker": worker}, job_id)
            self._refresh_job(db, job_id)
            return _one(db, "SELECT * FROM stages WHERE job_id=? AND name=?", (job_id, stage_name))

    @staticmethod
    def _lease(db, token, job_id=None):
        try:
            stage = _one(db, "SELECT * FROM stages WHERE lease_token=?", (token,))
        except NotFoundError as exc:
            raise ConflictError("Worker lease is stale or unknown") from exc
        if (stage["status"] != "running" or stage["lease_until"] <= utc_now()
                or job_id is not None and stage["job_id"] != job_id):
            raise ConflictError("Worker lease is expired, stale, or belongs to another job")
        return stage

    def heartbeat(self, token, lease_seconds=900):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValidationError("lease_seconds must be between 1 and 3600")
        with self.connection(True) as db:
            self._lease(db, token)
            until = timestamp((datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat())
            db.execute("UPDATE stages SET lease_until=?,updated_at=? WHERE lease_token=?", (until, utc_now(), token))
            return until

    def finish_stage(self, token, *, result=None, error=None):
        if error is not None:
            if not isinstance(error, dict) or not isinstance(error.get("retryable"), bool):
                raise ValidationError("Errors need code, message and boolean retryable")
            identifier(error.get("code"), "error code")
            nonempty(error.get("message"), "error message", 4000)
        if error is not None and result is not None:
            raise ValidationError("A stage cannot both succeed and fail")
        result_json = canonical_json(result or {}) if error is None else None
        error_json = canonical_json(error) if error is not None else None
        status = "failed" if error is not None else "succeeded"
        with self.connection(True) as db:
            attempt = _one(db, "SELECT * FROM attempts WHERE token=?", (token,))
            if attempt["status"] in ("succeeded", "failed"):
                if attempt["status"] == status and canonical_json(attempt["result"]) == (result_json or "null") and canonical_json(attempt["error"]) == (error_json or "null"):
                    return attempt
                raise ConflictError("Attempt already finished with a different result")
            stage = self._lease(db, token)
            now = utc_now()
            db.execute("UPDATE stages SET status=?,result_json=?,error_json=?,lease_until=NULL,updated_at=? WHERE lease_token=?",
                       (status, result_json, error_json, now, token))
            db.execute("UPDATE attempts SET status=?,finished_at=?,result_json=?,error_json=? WHERE token=?",
                       (status, now, result_json, error_json, token))
            self._event(db, "stage_" + status, {"stage": stage["name"], "error": error}, stage["job_id"])
            self._refresh_job(db, stage["job_id"])
            return _one(db, "SELECT * FROM attempts WHERE token=?", (token,))

    def retry_stage(self, job_id, stage_name, *, actor, reason):
        identifier(stage_name, "stage_name")
        nonempty(actor, "actor")
        nonempty(reason, "reason", 2000, multiline=True)
        with self.connection(True) as db:
            stage = _one(db, "SELECT * FROM stages WHERE job_id=? AND name=?", (job_id, stage_name))
            if stage["status"] != "failed" or stage["attempts"] >= stage["max_attempts"]:
                raise ConflictError("Stage is not failed or its attempt budget is exhausted")
            if not stage["error"].get("retryable", False):
                raise ConflictError("Failure is not retryable; fix inputs in a new versioned job")
            db.execute("UPDATE stages SET status='queued',lease_token=NULL,worker=NULL,updated_at=? WHERE job_id=? AND name=?",
                       (utc_now(), job_id, stage_name))
            self._event(db, "stage_retry_requested", {"stage": stage_name, "actor": actor, "reason": reason}, job_id)
            self._refresh_job(db, job_id)

    def skip_stage(self, job_id, stage_name, *, actor, reason):
        identifier(stage_name, "stage_name")
        nonempty(actor, "actor")
        nonempty(reason, "reason", 2000)
        with self.connection(True) as db:
            stage = _one(db, "SELECT * FROM stages WHERE job_id=? AND name=?", (job_id, stage_name))
            if stage["status"] != "queued" or stage["attempts"]:
                raise ConflictError("Only an unattempted queued stage can be explicitly skipped")
            if db.execute("SELECT 1 FROM stages WHERE job_id=? AND position<? AND status NOT IN ('succeeded','skipped')",
                          (job_id, stage["position"])).fetchone():
                raise ConflictError("Earlier stages are incomplete")
            result = {"skipped": True, "reason": reason, "actor": actor}
            db.execute("UPDATE stages SET status='skipped',result_json=?,updated_at=? WHERE job_id=? AND name=?",
                       (canonical_json(result), utc_now(), job_id, stage_name))
            self._event(db, "stage_skipped", {"stage": stage_name, **result}, job_id)
            self._refresh_job(db, job_id)

    def put_candidate(self, *, job_id, signal_key, target_id, mission, period_days, epoch,
                      epoch_system, duration_hours, detection, provenance_id, lease_token=None):
        if mission not in ("TESS", "Kepler"):
            raise ValidationError("mission must be TESS or Kepler")
        if not isinstance(detection, dict) or not detection:
            raise ValidationError("Detection method and input provenance must be recorded")
        nonempty(detection.get("method"), "detection method")
        if detection.get("ephemeris_origin") not in ("blind_search", "catalog_control", "synthetic_fixture"):
            raise ValidationError("Explicit ephemeris_origin is required")
        if detection["ephemeris_origin"] == "blind_search" and detection.get("used_catalog_ephemeris") is not False:
            raise ValidationError("Blind search must explicitly declare used_catalog_ephemeris=false")
        eph = ephemeris(period_days, epoch, epoch_system, duration_hours)
        now = utc_now()
        fields = {"id": uuid.uuid4().hex, "job_id": job_id, "signal_key": nonempty(signal_key, "signal_key"),
                  "target_id": nonempty(target_id, "target_id"), "mission": mission,
                  "ephemeris_json": canonical_json(eph), "detection_json": canonical_json(detection),
                  "provenance_id": provenance_id, "created_at": now, "updated_at": now}
        with self.connection(True) as db:
            job = _one(db, "SELECT * FROM jobs WHERE id=?", (job_id,))
            _one(db, "SELECT * FROM provenance WHERE id=?", (provenance_id,))
            if lease_token:
                self._lease(db, lease_token, job_id)
            origin = detection["ephemeris_origin"]
            if origin == "synthetic_fixture" and job["cohort"] != "synthetic_fixture":
                raise ValidationError("Synthetic candidates must belong to a synthetic fixture job")
            if origin == "catalog_control" and job["cohort"] != "known_object_control":
                raise ValidationError("Catalog ephemerides are only allowed as known-object controls")
            if job["product_id"]:
                product = _one(db, "SELECT * FROM products WHERE id=?", (job["product_id"],))
                release = _one(db, "SELECT * FROM releases WHERE id=?", (job["release_id"],))
                if target_id != product["target_id"] or mission != release["mission"]:
                    raise ValidationError("Candidate identity differs from its job product")
            old = db.execute("SELECT 1 FROM candidates WHERE job_id=? AND signal_key=?", (job_id, signal_key)).fetchone()
            candidate = self._immutable(db, "candidates", ("job_id", "signal_key"), fields)
            if not old:
                self._event(db, "candidate_recorded", {"signal_key": signal_key}, job_id, candidate["id"])
            return candidate

    def put_evidence(self, *, candidate_id, evidence_key, kind, state, summary, payload=None,
                     provenance_id=None, lease_token=None):
        identifier(kind, "evidence kind")
        nonempty(evidence_key, "evidence_key")
        nonempty(summary, "summary", 4000)
        if state not in EVIDENCE_STATES:
            raise ValidationError("Unsupported evidence state")
        if state == "complete" and (not provenance_id or not isinstance(payload, dict) or not payload):
            raise ValidationError("Complete evidence requires a provenance record and nonempty payload")
        if kind == "model_score" and state == "complete":
            finite_number(payload.get("score"), "model score", 0, 1)
            for key in ("model_sha256", "normalization_sha256"):
                sha256(payload.get(key))
            if payload.get("input_contract") != "shared_v1":
                raise ValidationError("Model evidence must name the shared_v1 input contract")
        if kind == "registry" and state == "complete":
            status = payload.get("status")
            nonempty(status, "registry status")
            if status == "INCOMPLETE_LOOKUP" or payload.get("required_sources_complete") is not True:
                raise ValidationError("Unavailable required catalogs must remain incomplete")
        with self.connection(True) as db:
            candidate = _one(db, "SELECT * FROM candidates WHERE id=?", (candidate_id,))
            if lease_token:
                self._lease(db, lease_token, candidate["job_id"])
            if provenance_id:
                _one(db, "SELECT * FROM provenance WHERE id=?", (provenance_id,))
            old = db.execute("SELECT 1 FROM evidence WHERE candidate_id=? AND evidence_key=?", (candidate_id, evidence_key)).fetchone()
            evidence = self._immutable(db, "evidence", ("candidate_id", "evidence_key"), {
                "id": uuid.uuid4().hex, "candidate_id": candidate_id, "evidence_key": evidence_key,
                "kind": kind, "state": state, "summary": summary, "payload_json": canonical_json(payload or {}),
                "provenance_id": provenance_id, "created_at": utc_now()})
            if not old:
                self._event(db, "evidence_recorded", {"kind": kind, "state": state, "id": evidence["id"]}, candidate["job_id"], candidate_id)
            return evidence

    def review_candidate(self, candidate_id, *, status, reviewer, note, expected_revision):
        if status not in REVIEW_STATUSES:
            raise ValidationError("Unsupported review status; the app cannot confirm a planet")
        nonempty(reviewer, "reviewer")
        nonempty(note, "review note", 4000, multiline=True)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValidationError("expected_revision must be a nonnegative integer")
        with self.connection(True) as db:
            candidate = _one(db, "SELECT * FROM candidates WHERE id=?", (candidate_id,))
            if candidate["revision"] != expected_revision:
                raise ConflictError("Review was changed elsewhere; reload before saving")
            revision = expected_revision + 1
            now = utc_now()
            db.execute("INSERT INTO reviews(candidate_id,revision,status,reviewer,note,created_at) VALUES(?,?,?,?,?,?)",
                       (candidate_id, revision, status, reviewer, note, now))
            db.execute("UPDATE candidates SET review_status=?,revision=?,updated_at=? WHERE id=?",
                       (status, revision, now, candidate_id))
            self._event(db, "review_updated", {"status": status, "reviewer": reviewer, "revision": revision}, candidate["job_id"], candidate_id)
            return {"id": candidate_id, "review_status": status, "revision": revision}

    def register_artifact(self, *, candidate_id, artifact_key, kind, media_type, filename,
                          sha256_digest, size_bytes, metadata=None, lease_token=None):
        # ArtifactStore is the public ingestion interface; it copies/verifies bytes.
        identifier(kind, "artifact kind")
        nonempty(artifact_key, "artifact_key")
        nonempty(filename, "filename")
        if media_type not in ARTIFACT_MEDIA_TYPES:
            raise ValidationError("Unsupported artifact media type")
        if Path(filename).name != filename or "\\" in filename:
            raise ValidationError("Artifact filenames must be plain basenames")
        sha256(sha256_digest)
        if type(size_bytes) is not int or not 0 <= size_bytes <= 64 * 1024 ** 2:
            raise ValidationError("Artifact exceeds 64 MiB")
        with self.connection(True) as db:
            candidate = _one(db, "SELECT * FROM candidates WHERE id=?", (candidate_id,))
            if lease_token:
                self._lease(db, lease_token, candidate["job_id"])
            return self._immutable(db, "artifacts", ("candidate_id", "artifact_key"), {
                "id": uuid.uuid4().hex, "candidate_id": candidate_id, "artifact_key": artifact_key, "kind": kind,
                "media_type": media_type, "filename": filename, "sha256": sha256_digest, "size_bytes": size_bytes,
                "metadata_json": canonical_json(metadata or {}), "created_at": utc_now()})

    def get_artifact(self, artifact_id):
        with self.connection() as db:
            return _one(db, "SELECT * FROM artifacts WHERE id=?", (artifact_id,))

    def list_records(self, table, *, limit=100, offset=0, cohort=None, review_status=None):
        if table not in ("jobs", "candidates", "releases", "products", "protocols"):
            raise ValidationError("Unsupported list")
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 200 or not 0 <= offset <= 1000000:
            raise ValidationError("Invalid pagination")
        parameters, clauses = [], []
        if table == "candidates":
            query = "SELECT t.*,j.cohort,j.status AS job_status FROM candidates t JOIN jobs j ON j.id=t.job_id"
        else:
            query = f"SELECT t.* FROM {table} t"
        if cohort is not None:
            if cohort not in COHORTS or table not in ("jobs", "candidates"):
                raise ValidationError("Invalid cohort filter")
            clauses.append(("j" if table == "candidates" else "t") + ".cohort=?")
            parameters.append(cohort)
        if review_status is not None:
            if review_status not in REVIEW_STATUSES or table != "candidates":
                raise ValidationError("Invalid review filter")
            clauses.append("t.review_status=?")
            parameters.append(review_status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.created_at DESC,t.id DESC LIMIT ? OFFSET ?"
        with self.connection() as db:
            rows = _rows(db, query, (*parameters, limit, offset))
            if table == "candidates":
                for row in rows:
                    row["assessment"] = compact_assessment(_rows(db,
                        "SELECT * FROM evidence WHERE candidate_id=? AND kind IN ('model_score','registry') ORDER BY rowid", (row["id"],)))
            return rows

    @staticmethod
    def _job(db, job_id):
        job = _one(db, "SELECT * FROM jobs WHERE id=?", (job_id,))
        job["stages"] = _rows(db, "SELECT * FROM stages WHERE job_id=? ORDER BY position", (job_id,))
        job["attempt_history"] = _rows(db, "SELECT * FROM attempts WHERE job_id=? ORDER BY started_at", (job_id,))
        job["events"] = _rows(db, "SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,))
        return job

    def get_job(self, job_id):
        with self.connection() as db:
            return self._job(db, job_id)

    def get_candidate(self, candidate_id):
        with self.connection() as db:
            candidate = _one(db, "SELECT * FROM candidates WHERE id=?", (candidate_id,))
            job = self._job(db, candidate["job_id"])
            protocol = _one(db, "SELECT * FROM protocols WHERE id=?", (job["protocol_id"],))
            history = _rows(db, "SELECT * FROM evidence WHERE candidate_id=? ORDER BY rowid", (candidate_id,))
            latest = {item["kind"]: item for item in history}
            required = protocol["document"]["required_evidence"]
            gaps = [kind for kind in required if kind not in latest or latest[kind]["state"] != "complete"]
            candidate.update(cohort=job["cohort"], job=job, protocol=protocol, evidence=list(latest.values()),
                             evidence_history=history, incomplete_evidence=gaps,
                             evidence_state="incomplete" if gaps else "recorded",
                             artifacts=_rows(db, "SELECT * FROM artifacts WHERE candidate_id=? ORDER BY created_at", (candidate_id,)),
                             reviews=_rows(db, "SELECT * FROM reviews WHERE candidate_id=? ORDER BY revision", (candidate_id,)))
            ids = {candidate["provenance_id"], job["code_provenance_id"]}
            ids.update(e["provenance_id"] for e in history if e["provenance_id"])
            candidate["release"] = _one(db, "SELECT * FROM releases WHERE id=?", (job["release_id"],)) if job["release_id"] else None
            candidate["product"] = _one(db, "SELECT * FROM products WHERE id=?", (job["product_id"],)) if job["product_id"] else None
            for record in (candidate["release"], candidate["product"]):
                if record:
                    ids.add(record["provenance_id"])
            candidate["provenance"] = [_one(db, "SELECT * FROM provenance WHERE id=?", (p,)) for p in sorted(ids)]
            candidate["warnings"] = ["Scores rank evidence; they are not planet-confirmation probabilities.",
                                     "UNMATCHED is not proof of novelty. Missing diagnostics remain incomplete.",
                                     "A completed job records execution, not scientific validation."]
            candidate["review_triage"] = review_flags(candidate)
            candidate["assessment"] = compact_assessment(candidate["evidence"])
            return candidate

    def summary(self):
        with self.connection() as db:
            return {"schema_version": SCHEMA_VERSION,
                    "jobs_by_status": {r["status"]: r["n"] for r in db.execute("SELECT status,count(*) n FROM jobs GROUP BY status")},
                    "candidates_by_cohort": {r["cohort"]: r["n"] for r in db.execute("SELECT j.cohort,count(*) n FROM candidates c JOIN jobs j ON j.id=c.job_id GROUP BY j.cohort")},
                    "release_count": db.execute("SELECT count(*) FROM releases").fetchone()[0],
                    "product_count": db.execute("SELECT count(*) FROM products").fetchone()[0],
                    "expired_running_stages": db.execute("SELECT count(*) FROM stages WHERE status='running' AND lease_until<=?", (utc_now(),)).fetchone()[0],
                    "watcher": "bounded_MAST_metadata_and_explicit_pilot", "detection": "bounded_local_blind_bls_v1",
                    "pixel_photometry": "not_implemented", "tls": "not_implemented",
                    "scoring": "frozen_shared_v1_CNN_cpu", "vetting": "bounded_diagnostics_and_catalog_cache",
                    "search_readiness": False,
                    "observed_at": utc_now()}
