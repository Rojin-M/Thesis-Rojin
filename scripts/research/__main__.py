"""Run the local research foundation: python -m scripts.research --help."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import signal
import sys
import threading

from .artifacts import ArtifactStore
from .fixtures import seed_fixture
from .protocol import DEFAULT_PROTOCOL, ROOT, load_protocol
from .reports import dossier, markdown_report
from .server import ResearchServer
from .store import Store


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=ROOT / "outputs/research/research.sqlite3")
    p.add_argument("--artifacts", type=Path, default=ROOT / "outputs/research/artifacts")
    p.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize schema and register the immutable bounded protocol; no data or jobs")
    sub.add_parser("status", help="Print persisted counts and the current protocol hash")
    sub.add_parser("recover", help="Requeue expired worker leases within their attempt budgets")
    sub.add_parser("watch-auto-check", help="Ask the running automatic watcher to check for new data now")
    for command in ("watch-auto-once", "watch-auto-serve"):
        automatic = sub.add_parser(command, help="Poll the configured watchlist and automatically detect/vet unseen products within cumulative bounds")
        automatic.add_argument("--config", type=Path, default=ROOT / "configs/research_automation_v1.json")
        if command == "watch-auto-once":
            automatic.add_argument("--force", action="store_true", help="Recheck public metadata now while retaining circuit and resource limits")
        else:
            automatic.add_argument("--max-hours", type=float, help="Optional finite lifetime, up to 168 hours; otherwise run until stopped")
    for command in ("watch-poll", "watch-serve", "watch-reset"):
        watcher = sub.add_parser(command, help="Bounded public MAST metadata only; never auto-select science downloads")
        watcher.add_argument("--config", type=Path, default=ROOT / "configs/research_watcher_v1.json")
        if command == "watch-poll":
            watcher.add_argument("--force", action="store_true", help="Ignore next poll time, but retain the three-failure circuit cap")
        if command == "watch-serve":
            watcher.add_argument("--max-hours", type=float, default=12, help="Finite metadata-only service lifetime, at most 12 h")
    sub.add_parser("watch-status", help="Show persisted poll health, errors, queue and cumulative budgets")
    account = sub.add_parser("watch-account", help="Import already-consumed network bytes once into the cumulative ledger")
    account.add_argument("--key", required=True)
    account.add_argument("--bytes", type=int, required=True)
    account.add_argument("--reason", required=True)
    pilot = sub.add_parser("watch-pilot", help="Freeze an explicit finite observed-product selection; does not download")
    pilot.add_argument("--pilot-id", required=True)
    pilot.add_argument("--product-id", action="append", required=True)
    pilot.add_argument("--cohort", choices=("known_object_control", "archival_pilot"), required=True)
    pilot.add_argument("--max-bytes", type=int, required=True)
    pilot.add_argument("--max-seconds", type=int, required=True)
    dispatcher = sub.add_parser("watch-dispatch", help="Resume only one frozen pilot, with cumulative byte/time/retry caps")
    dispatcher.add_argument("--pilot-id", required=True)
    repin = sub.add_parser("watch-repin", help="Explicitly replace a failed unacquired pilot source pin without resetting attempts or budgets")
    repin.add_argument("--pilot-id", required=True)
    repin.add_argument("--replacement-id", required=True)
    repin.add_argument("--reason", required=True)
    sub.add_parser("seed-fixture", help="Explicitly add a SYNTHETIC demonstration; prefer a separate database")
    controls = sub.add_parser("detection-controls", help="Four TRAIN-star controls, six injections and four negatives; no downloads")
    controls.add_argument("--output", type=Path, required=True, help="New versioned local experiment directory")
    vet = sub.add_parser("vet", help="Resume explicit detected jobs through shared inputs, frozen CNN, diagnostics and dossiers")
    vet.add_argument("--job-id", action="append", required=True, help="Repeat for at most 20 persisted job IDs")
    vet.add_argument("--catalog-mode", choices=("offline", "live"), default="offline")
    vet.add_argument("--feature-seconds", type=int, default=300)
    vet.add_argument("--retry-failed", action="store_true", help="Explicitly queue retryable failed downstream stages within their attempt caps")
    refresh = sub.add_parser("refresh-registry", help="Append bounded catalog assessments; refresh does not rescore or reject proposals")
    refresh.add_argument("--candidate-id", action="append", required=True)
    refresh.add_argument("--catalog-mode", choices=("offline", "live"), default="offline")
    refresh.add_argument("--force", action="store_true", help="Bypass cache TTL to retry/revalidate sources; network only with live mode")
    detect = sub.add_parser("detect", help="Run bounded blind BLS on explicit local FITS/CSV/NPZ files; persist proposals")
    source = detect.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", type=Path, action="append", help="Local source product; repeat for at most 20 files")
    source.add_argument("--cached-tess", action="store_true", help="Select earliest cached public TESS products from the existing manifest")
    detect.add_argument("--max-products", type=int, default=1, help="Cached TESS selection cap, at most 20")
    detect.add_argument("--mission", choices=("TESS", "Kepler"), required=True)
    detect.add_argument("--target-id", required=True)
    detect.add_argument("--cohort", choices=("known_object_control", "archival_pilot", "synthetic_fixture"), required=True)
    detect.add_argument("--time-system", choices=("BJD_TDB", "BTJD", "BKJD"), help="Required for CSV/NPZ; native FITS use headers")
    detect.add_argument("--job-key", help="Explicit versioned identity; identical reruns resume/deduplicate")
    for flag in ("period-min-days", "period-max-days"):
        detect.add_argument("--" + flag, type=float)
    for flag in ("max-period-grid", "max-signals", "max-seconds"):
        detect.add_argument("--" + flag, type=int)
    export = sub.add_parser("export", help="Export one complete candidate dossier")
    export.add_argument("candidate_id")
    export.add_argument("--format", choices=("json", "md"), default="json")
    export.add_argument("--output", type=Path, required=True)
    server = sub.add_parser("serve", help="Serve the local UI/API; does not start a watcher or pipeline")
    server.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    server.add_argument("--port", type=int, default=8766)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(args.db).initialize()
    protocol = store.register_protocol(load_protocol(args.protocol))
    artifacts = ArtifactStore(args.artifacts, store)
    if args.command == "watch-auto-check":
        from .watcher_store import WatchStore
        print(json.dumps(WatchStore(store).request_check(), indent=2))
    elif args.command.startswith("watch-auto-"):
        from .automation import load_config, run_cycle, serve_automatic
        from .watcher_store import WatchStore, exclusive_lock
        config = load_config(args.config)
        if args.command == "watch-auto-once":
            with exclusive_lock(store.path.with_suffix('.watch-service.lock')):
                ledger = WatchStore(store)
                ledger.automation_update(state='stopped')
                try:
                    result = run_cycle(store, artifacts, protocol["id"], config, force=args.force)
                finally:
                    ledger.automation_update(state='stopped')
            print(json.dumps(result, indent=2))
            return int(bool(result["errors"]))
        serve_automatic(store, artifacts, protocol["id"], config, max_hours=args.max_hours)
    elif args.command.startswith("watch-"):
        from .watcher import load_config, poll_once, create_pilot, dispatch, serve_metadata, repin_failed_pilot
        from .watcher_store import WatchStore, status, exclusive_lock
        ledger = WatchStore(store)
        if args.command == "watch-status":
            result = status(store)
        elif args.command == "watch-account":
            result = {"spending_id": ledger.account(args.key, args.bytes, args.reason)}
        elif args.command == "watch-pilot":
            result = create_pilot(store, protocol["id"], pilot_id=args.pilot_id, product_ids=args.product_id,
                cohort=args.cohort, max_bytes=args.max_bytes, max_seconds=args.max_seconds)
        elif args.command == "watch-dispatch":
            result = dispatch(store, artifacts, args.pilot_id)
        elif args.command == "watch-repin":
            result = repin_failed_pilot(store, pilot_id=args.pilot_id, replacement_id=args.replacement_id, reason=args.reason)
        else:
            config = load_config(args.config)
            if args.command == "watch-poll":
                result = poll_once(store, config, force=args.force)
            elif args.command == "watch-reset":
                with exclusive_lock(ledger.lock_path):
                    ledger.reset(ledger.config(config)["id"])
                result = {"status": "reset", "mode": "metadata_only"}
            else:
                serve_metadata(store, config, max_hours=args.max_hours)
                result = {"status": "stopped", "mode": "metadata_only"}
        print(json.dumps(result, indent=2))
        if result.get("status") in ("failed", "runtime_exhausted"):
            return 1
    elif args.command in ("init", "status"):
        print(json.dumps({"database": str(store.path), "protocol_id": protocol["id"], **store.summary()}, indent=2))
    elif args.command == "recover":
        print(json.dumps({"recovered_stages": store.recover_expired()}))
    elif args.command == "seed-fixture":
        candidate = seed_fixture(store, artifacts, protocol["id"])
        print(json.dumps({"cohort": "synthetic_fixture", "candidate_id": candidate["id"],
                          "url_fragment": "#candidate/" + candidate["id"]}, indent=2))
    elif args.command == "detect":
        from .detection import SearchConfig
        from .detection_worker import run_local_detection
        from .local_selection import cached_tess_paths
        overrides = {key: getattr(args, key) for key in ("period_min_days", "period_max_days", "max_period_grid", "max_signals", "max_seconds")
                     if getattr(args, key) is not None}
        paths = args.path
        if args.cached_tess:
            if args.mission != "TESS":
                raise ValueError("--cached-tess requires --mission TESS")
            paths = cached_tess_paths(ROOT, args.target_id, args.max_products)
        result = run_local_detection(store, artifacts, protocol["id"], paths=paths, mission=args.mission,
            target_id=args.target_id, cohort=args.cohort, time_system=args.time_system, job_key=args.job_key,
            config=SearchConfig.from_protocol(protocol["document"], **overrides))
        print(json.dumps(result, indent=2, allow_nan=False))
    elif args.command == "detection-controls":
        from .detection_controls import run_controls
        print(json.dumps(run_controls(store, artifacts, protocol["id"], args.output), indent=2))
    elif args.command == "vet":
        from .vetting_worker import run_vetting
        ids = list(dict.fromkeys(args.job_id))
        if not 1 <= len(ids) <= 20:
            raise ValueError("Select 1–20 explicit jobs")
        bundles, outcomes = {}, []
        for job_id in ids:
            try:
                if args.retry_failed:
                    for stage in store.get_job(job_id)["stages"]:
                        if stage["name"] in ("features", "scoring", "diagnostics", "dossier") and stage["status"] == "failed" and stage["error"].get("retryable"):
                            store.retry_stage(job_id, stage["name"], actor="local-vet-cli", reason="Explicit --retry-failed operator request")
                outcomes.append(run_vetting(store, artifacts, job_id, catalog_mode=args.catalog_mode,
                                            feature_seconds=args.feature_seconds, bundles=bundles))
            except (ValueError, LookupError, OSError, RuntimeError) as exc:
                outcomes.append({"job_id": job_id, "error": str(exc), "error_type": type(exc).__name__})
        print(json.dumps({"jobs": outcomes, "mode": args.catalog_mode}, indent=2, allow_nan=False))
        return int(any("error" in outcome for outcome in outcomes))
    elif args.command == "refresh-registry":
        from .vetting_worker import refresh_registry
        print(json.dumps(refresh_registry(store, artifacts, args.candidate_id, mode=args.catalog_mode,
                                         force=args.force), indent=2, allow_nan=False))
    elif args.command == "export":
        document = dossier(store, args.candidate_id)
        payload = json.dumps(document, indent=2, allow_nan=False) + "\n" if args.format == "json" else markdown_report(document)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # A versioned research export must never silently overwrite a report.
        with args.output.open("x") as handle:
            handle.write(payload)
        print(str(args.output.resolve()))
    elif args.command == "serve":
        if not 1 <= args.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        # No startup reset of running jobs: only leases that really expired are
        # recoverable. Active worker state survives a website restart.
        recovered = store.recover_expired()
        server = ResearchServer((args.host, args.port), store, artifacts, protocol["id"])
        def stop(_signum, _frame):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        print(f"Research pilot at http://{args.host}:{args.port}; database={store.path}; expired leases recovered={recovered}", flush=True)
        try:
            server.serve_forever(poll_interval=.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, LookupError, OSError) as exc:
        print(f"research: {exc}", file=sys.stderr)
        sys.exit(1)
