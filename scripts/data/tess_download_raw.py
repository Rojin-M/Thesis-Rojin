#!/usr/bin/env python3
"""Acquire TOI metadata and native 120-second SPOC light curves for TESS.

Like the Kepler downloader, --base_dir names the project/data root. Original
FITS and a frozen query manifest are saved under data/raw/tess. This stage
does not prepare training features or assign final labels to transit events.
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
import warnings

import numpy as np
import pandas as pd
import requests
from astropy.io import fits
from astropy.table import Table
from astroquery.mast import Observations


TOI_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
DOWNLOAD_URL = "https://mast.stsci.edu/api/v0.1/Download/file"
REQUIRED_COLUMNS = {"tid", "toi", "tfopwg_disp", "pl_orbper", "pl_tranmid", "pl_trandurh"}
LC_NAME = re.compile(r"^tess\d+-s(?P<sector>\d{4})-(?P<tic>\d{16})-\d+-[a-z]_lc\.fits$")
MANIFEST_COLUMNS = ["tic_id", "sector", "cadence_seconds", "obs_id", "data_uri", "filename", "relative_path"]
LOG = logging.getLogger("tess_download_raw")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def save_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def save_csv(path, rows, columns):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, output.getvalue().encode())


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def retry(operation, attempts=3, stop_event=None):
    for attempt in range(attempts):
        if stop_event is not None and stop_event.is_set():
            raise CancelledError()
        try:
            return operation()
        except (requests.RequestException, OSError, RuntimeError, ValueError) as error:
            if attempt + 1 == attempts:
                raise
            LOG.warning("Retry %d/%d after %s: %s", attempt + 1, attempts, type(error).__name__, error)
            if stop_event is None:
                time.sleep(2 ** (attempt + 1))
            else:
                stop_event.wait(2 ** (attempt + 1))


def read_catalog(content):
    catalog = pd.read_csv(io.BytesIO(content), dtype={"toi": str, "tid": str}, keep_default_na=False)
    if catalog.empty or not REQUIRED_COLUMNS.issubset(catalog.columns):
        raise ValueError("Expected a nonempty NASA TOI catalog with the required columns")
    if not catalog.tid.str.fullmatch(r"[0-9]+").all() or catalog.toi.duplicated().any():
        raise ValueError("Invalid TIC identifiers or duplicate TOI identifiers in catalog")
    catalog["tid"] = catalog.tid.map(lambda value: str(int(value)))
    catalog["tfopwg_disp"] = catalog.tfopwg_disp.str.strip().str.upper()
    return catalog


def acquire_catalog(metadata, session):
    path, provenance_path = metadata / "toi.csv", metadata / "provenance.json"
    if path.exists():
        if not provenance_path.exists():
            raise ValueError("Cached catalog lacks provenance; use a fresh --base_dir")
        provenance = json.loads(provenance_path.read_text())
        if sha256(path) != provenance["catalog_sha256"]:
            raise ValueError("Cached catalog differs from its recorded checksum")
        return read_catalog(path.read_bytes())

    def fetch():
        LOG.info("Fetching current NASA TOI catalog")
        with session.get(TOI_URL, params={"query": "select * from toi", "format": "csv"},
                         timeout=(30, 180)) as response:
            response.raise_for_status()
            content = response.content
            catalog = read_catalog(content)
            # A catalog is published only after its provenance is safely written.
            save_json(provenance_path, {
                "catalog_url": response.url, "catalog_retrieved_utc": utc_now(),
                "catalog_sha256": hashlib.sha256(content).hexdigest(),
                "epoch_units": "TOI pl_tranmid: BJD; pl_trandurh: hours",
            })
            atomic_bytes(path, content)
            return catalog

    return retry(fetch)


def select_targets(catalog, dispositions, tics=()):
    selected = catalog.tfopwg_disp.isin(dispositions)
    targets = sorted(set(catalog.loc[selected, "tid"]), key=int)
    if tics:
        missing = set(tics) - set(targets)
        if missing:
            raise ValueError(f"Requested TICs lack selected TOI dispositions: {sorted(missing)}")
        targets = [tic for tic in targets if tic in set(tics)]
    if not targets:
        raise ValueError("No TOI stars match the selection")
    # A star can host several transit candidates with conflicting dispositions.
    # Retain unknown companions as well; never turn a star ID into a class label.
    candidates = catalog[catalog.tid.isin(targets)].copy()
    candidates["selected_disposition"] = candidates.tfopwg_disp.isin(dispositions)
    return targets, candidates


def select_lightcurves(observations, targets, max_sector):
    selected = {}
    for observation in observations:
        if (str(observation["obs_collection"]) != "TESS"
                or str(observation["provenance_name"]) != "SPOC"):
            continue
        cadence, sector = observation["t_exptime"], observation["sequence_number"]
        if np.ma.is_masked(cadence) or np.ma.is_masked(sector):
            continue
        if not 119 <= float(cadence) <= 121 or not 1 <= int(sector) <= max_sector:
            continue
        uri = str(observation["dataURL"])
        if not uri.startswith("mast:TESS/product/"):
            continue
        filename = uri.removeprefix("mast:TESS/product/")
        match = LC_NAME.fullmatch(filename)
        if not match:
            continue  # Excludes validation time series, pixels and fast cadences.
        tic = str(int(match["tic"]))
        if tic not in targets or tic != str(observation["target_name"]) or int(match["sector"]) != int(sector):
            continue
        selected[uri] = {
            "tic_id": tic, "sector": int(sector), "cadence_seconds": 120,
            "obs_id": str(observation["obs_id"]), "data_uri": uri, "filename": filename,
            "relative_path": f"lightcurves/TIC{tic}/{filename}",
        }
    return sorted(selected.values(), key=lambda row: (int(row["tic_id"]), row["sector"], row["filename"]))


def build_manifest(metadata, targets, max_sector):
    manifest, provenance_path = metadata / "manifest.csv", metadata / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    if manifest.exists():
        if sha256(manifest) != provenance.get("manifest_sha256"):
            raise ValueError("Cached manifest differs from its recorded checksum")
        with manifest.open(newline="") as stream:
            return list(csv.DictReader(stream))
    selected, queries = {}, []
    for start in range(0, len(targets), 100):
        batch = targets[start:start + 100]
        path = metadata / "mast_queries" / f"observations_{start:06d}.ecsv"
        LOG.info("Finding light curves for stars %d–%d/%d", start + 1, start + len(batch), len(targets))
        if path.exists():
            observations = Table.read(path, format="ascii.ecsv")
        else:
            observations = retry(lambda: Observations.query_criteria(
                obs_collection="TESS", provenance_name="SPOC", target_name=batch,
                dataproduct_type="timeseries", t_exptime=[119, 121],
            ))
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".part")
            observations.write(temporary, format="ascii.ecsv", overwrite=True)
            temporary.replace(path)
        queries.append({"file": str(path.relative_to(metadata)), "sha256": sha256(path)})
        for record in select_lightcurves(observations, set(batch), max_sector):
            selected[record["data_uri"]] = record
    rows = sorted(selected.values(), key=lambda row: (int(row["tic_id"]), row["sector"], row["filename"]))
    counts = dict.fromkeys(targets, 0)
    for row in rows:
        counts[row["tic_id"]] += 1
    coverage = [{"tic_id": tic, "lightcurve_files": counts[tic],
                 "status": "available" if counts[tic] else "no_spoc_120s_lightcurve"} for tic in targets]
    save_csv(metadata / "target_coverage.csv", coverage, ["tic_id", "lightcurve_files", "status"])
    # Publish the final manifest only when all queries have completed.
    staged = metadata / "manifest.pending.csv"
    save_csv(staged, rows, MANIFEST_COLUMNS)
    provenance.update({"manifest_created_utc": utc_now(), "manifest_sha256": sha256(staged),
                       "mast_query_files": queries, "product_lookup": "observation dataURL"})
    save_json(provenance_path, provenance)
    staged.replace(manifest)
    return rows


def validate_fits(path, product):
    if path.stat().st_size == 0 or path.stat().st_size % 2880:
        raise ValueError("Incomplete FITS file")
    with warnings.catch_warnings():
        warnings.simplefilter("error", fits.verify.VerifyWarning)
        with fits.open(path, memmap=False) as hdus:
            hdus.verify("exception")
            if (int(hdus[0].header.get("TICID", -1)) != int(product["tic_id"])
                    or int(hdus[0].header.get("SECTOR", -1)) != int(product["sector"])):
                raise ValueError("FITS TICID/SECTOR differs from requested observation")
            if len(hdus) < 2 or not {"TIME", "PDCSAP_FLUX", "QUALITY"}.issubset(hdus[1].columns.names):
                raise ValueError("Missing required light-curve columns")
            # Force reading the table: a missing complete 2880-byte block would
            # pass the size-divisibility check alone.
            if len(hdus[1].data) == 0:
                raise ValueError("Empty light-curve table")
            for hdu in hdus:
                if "CHECKSUM" in hdu.header and "DATASUM" not in hdu.header:
                    # SPOC omits DATASUM. Astropy 6's verify_checksum then
                    # assumes a zero data sum and rejects valid SPOC tables.
                    # Recompute using the public API, retaining the comment
                    # and header order. This only changes the in-memory HDU;
                    # the original FITS is opened read-only and kept intact.
                    expected = hdu.header["CHECKSUM"]
                    hdu.add_checksum(when=hdu.header.comments["CHECKSUM"], override_datasum=True)
                    checksum_valid = hdu.header["CHECKSUM"] == expected
                else:
                    checksum_valid = hdu.verify_checksum() != 0
                if not checksum_valid or hdu.verify_datasum() == 0:
                    raise ValueError("FITS checksum validation failed")


def download_lightcurve(raw_root, product, session, attempts=3, stop_event=None):
    path = raw_root / product["relative_path"]
    receipt = raw_root / "metadata" / "receipts" / (product["filename"] + ".json")
    if path.is_file() and receipt.is_file():
        try:
            saved = json.loads(receipt.read_text())
            if (saved["data_uri"] == product["data_uri"] and saved["size_bytes"] == path.stat().st_size
                    and saved["sha256"] == sha256(path)):
                return {**saved, "status": "cached"}
        except (ValueError, KeyError, OSError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")

    def fetch():
        digest, size = hashlib.sha256(), 0
        with session.get(DOWNLOAD_URL, params={"uri": product["data_uri"]}, stream=True,
                         headers={"Accept-Encoding": "identity"}, timeout=(15, 60)) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if stop_event is not None and stop_event.is_set():
                        raise CancelledError()
                    stream.write(block)
                    digest.update(block)
                    size += len(block)
            declared = response.headers.get("Content-Length")
            if declared is not None and size != int(declared):
                raise ValueError(f"Incomplete response: received {size}, expected {declared} bytes")
        validate_fits(temporary, product)
        temporary.replace(path)
        saved = {"data_uri": product["data_uri"], "relative_path": product["relative_path"],
                 "size_bytes": size, "sha256": digest.hexdigest(), "downloaded_utc": utc_now()}
        save_json(receipt, saved)
        return {**saved, "status": "downloaded"}

    return retry(fetch, attempts=attempts, stop_event=stop_event)


def run_downloads(raw_root, products, workers):
    stop_event, local, sessions = threading.Event(), threading.local(), []

    def work(product):
        if stop_event.is_set():
            raise CancelledError()
        if not hasattr(local, "session"):
            local.session = requests.Session()
            sessions.append(local.session)
        return download_lightcurve(raw_root, product, local.session, stop_event=stop_event)

    pool = ThreadPoolExecutor(max_workers=workers)
    futures, failures = {}, []
    completed, cached, size, interrupted = 0, 0, 0, False
    started = utc_now()
    try:
        futures = {pool.submit(work, product): product for product in products}
        for index, future in enumerate(as_completed(futures), 1):
            product = futures[future]
            try:
                result = future.result()
                completed += 1
                cached += result["status"] == "cached"
                size += result["size_bytes"]
                LOG.info("[%d/%d] %s: %s", index, len(products), result["status"], product["filename"])
            except Exception as error:
                failures.append({"data_uri": product["data_uri"], "error": str(error)})
                LOG.error("[%d/%d] %s: %s", index, len(products), product["filename"], error)
    except KeyboardInterrupt:
        interrupted = True
        stop_event.set()
        LOG.warning("Stopping workers; rerun the same command to resume completed files")
    finally:
        pool.shutdown(wait=True, cancel_futures=interrupted)
        for session in sessions:
            session.close()
    summary = {"started_utc": started, "finished_utc": utc_now(), "download_workers": workers,
               "planned_files": len(products), "completed_files": completed,
               "downloaded_files": completed - cached, "verified_existing_files": cached,
               "completed_bytes": size, "failed_files": len(failures),
               "status": "interrupted" if interrupted else "incomplete" if failures else "complete"}
    save_json(raw_root / "metadata" / "download_failures.json", failures)
    save_json(raw_root / "metadata" / "download_summary.json", summary)
    LOG.info("Download summary: %s", json.dumps(summary))
    return 130 if interrupted else 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True, help="Base project/data directory, as for Kepler")
    parser.add_argument("--max_sector", type=int, default=105, help="Include sectors 1 through this sector")
    parser.add_argument("--download_workers", type=int, default=1, help="Simultaneous files; default 1, use 4 for faster retrieval")
    parser.add_argument("--dispositions", nargs="+", default=["CP", "KP", "FP", "FA"],
                        choices=["CP", "KP", "FP", "FA", "PC", "APC"], help="TOI statuses used to select stars")
    parser.add_argument("--tic", action="append", default=[], help="Optional TIC ID for a small pilot; repeat for multiple stars")
    parser.add_argument("--dry_run", action="store_true", help="Save the catalog and manifest, without downloading FITS")
    args = parser.parse_args(argv)
    if args.max_sector < 1 or args.download_workers < 1:
        parser.error("--max_sector and --download_workers must be positive")
    if any(not tic.isdigit() for tic in args.tic):
        parser.error("--tic expects a numeric TIC ID")
    base = args.base_dir.resolve()
    raw_root, log_dir = base / "data" / "raw" / "tess", base / "logs"
    metadata = raw_root / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    for handler in LOG.handlers[:]:
        LOG.removeHandler(handler)
        handler.close()
    for handler in [logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / "tess_download_raw.log")]:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
    config = {"schema_version": 1, "mission": "TESS", "author": "SPOC", "cadence_seconds": 120,
              "product": "lightcurve", "max_sector": args.max_sector,
              "dispositions": sorted(set(args.dispositions)),
              "tic_filter": sorted(set(str(int(tic)) for tic in args.tic), key=int)}
    # Hold one lock across discovery and transfers. Parallel workers run inside
    # this process; separate copies must not write to the same raw directory.
    with (metadata / "download.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another downloader is already using this TESS directory")
        config_path = metadata / "config.json"
        if config_path.exists():
            if json.loads(config_path.read_text()) != config:
                raise ValueError("Data selection changed; choose a fresh --base_dir")
        else:
            save_json(config_path, config)
        with requests.Session() as session:
            catalog = acquire_catalog(metadata, session)
        targets, candidates = select_targets(catalog, config["dispositions"], config["tic_filter"])
        atomic_bytes(metadata / "candidates.csv", candidates.to_csv(index=False).encode())
        LOG.info("Selected %d stars; retained %d candidate rows", len(targets), len(candidates))
        products = build_manifest(metadata, targets, args.max_sector)
        LOG.info("Plan: %d light-curve files for %d stars; %d download worker(s)",
                 len(products), len({row["tic_id"] for row in products}), args.download_workers)
        if not products:
            raise RuntimeError("No matching light curves; see metadata/target_coverage.csv")
        if args.dry_run:
            LOG.info("Metadata saved. Rerun without --dry_run to download light curves")
            return 0
        result = run_downloads(raw_root, products, args.download_workers)
        LOG.info("Raw acquisition only; candidate matching, preprocessing and star-level splits remain")
        return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        LOG.warning("Interrupted; rerun the same command to resume")
        sys.exit(130)
    except Exception as error:
        LOG.error("%s", error)
        sys.exit(1)
