"""Check TESS candidate identity, model-input selection, and resumable integrity."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import requests
from astropy.io import fits
from astropy.table import Table

from scripts.data.tess_download_raw import (
    build_manifest,
    download_lightcurve,
    run_downloads,
    select_lightcurves,
    select_targets,
)


def lightcurve_bytes(tic_id=42, sector=1, include_quality=True):
    """A real, small FITS file, so transfer validation exercises FITS semantics."""
    primary = fits.PrimaryHDU()
    primary.header["TICID"] = tic_id
    primary.header["SECTOR"] = sector
    columns = [
        fits.Column(name="TIME", format="D", array=np.array([1325.0, 1325.0014])),
        fits.Column(name="PDCSAP_FLUX", format="E", array=np.array([1000.0, 999.0])),
    ]
    if include_quality:
        columns.append(fits.Column(name="QUALITY", format="J", array=np.array([0, 0])))
    output = io.BytesIO()
    fits.HDUList([primary, fits.BinTableHDU.from_columns(columns)]).writeto(output)
    return output.getvalue()


class StreamResponse:
    """The requests response surface used by the download function, without HTTP."""

    def __init__(self, payload, content_length=True):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))} if content_length else {}
        self.status_code = 200
        self.url = "https://mast.stsci.edu/api/v0.1/Download/file"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        # Split FITS blocks across stream chunks to exercise streaming assembly.
        for offset in range(0, len(self.payload), 997):
            yield self.payload[offset : offset + 997]


class TessSelectionTests(unittest.TestCase):
    def test_preserves_unconfirmed_companions_without_assigning_star_labels(self):
        catalog = pd.DataFrame(
            {
                "tid": ["42", "42", "7", "10", "99", "777"],
                "toi": ["42.01", "42.02", "7.01", "10.01", "99.01", "777.01"],
                "tfopwg_disp": ["CP", "PC", "FP", "FA", "KP", "APC"],
                "pl_orbper": [2.0, 4.0, 3.0, 5.0, 10.0, 12.0],
            }
        )
        original = catalog.copy(deep=True)
        targets, candidates = select_targets(catalog, ["CP", "KP", "FP", "FA"])
        self.assertEqual(targets, ["7", "10", "42", "99"])
        self.assertEqual(set(candidates["toi"]), {"42.01", "42.02", "7.01", "10.01", "99.01"})
        selected = candidates.set_index("toi")["selected_disposition"]
        self.assertTrue(selected["42.01"])
        self.assertFalse(selected["42.02"])
        self.assertNotIn("y", candidates.columns)
        self.assertEqual(candidates.set_index("toi").loc["42.02", "pl_orbper"], 4.0)
        pd.testing.assert_frame_equal(catalog, original)

    def test_selects_only_native_spoc_two_minute_lightcurves_and_deduplicates(self):
        def observation(tic=42, sector=1, cadence=120.0, author="SPOC", mission="TESS", suffix="s_lc.fits"):
            obs_id = f"tess2020000000000-s{sector:04d}-{tic:016d}-0001-s"
            filename = f"tess2020000000000-s{sector:04d}-{tic:016d}-0001-{suffix}"
            return {
                "target_name": str(tic),
                "sequence_number": sector,
                "t_exptime": cadence,
                "provenance_name": author,
                "obs_collection": mission,
                "obs_id": obs_id,
                "dataURL": f"mast:TESS/product/{filename}",
            }

        first = observation()
        observations = Table(
            rows=[
                first,
                dict(first),  # A duplicate archive row must not trigger a second transfer.
                observation(tic=7, sector=2),
                observation(cadence=20.0, suffix="a_fast-lc.fits"),
                observation(author="QLP"),
                observation(author="TESS-SPOC"),
                observation(mission="Kepler"),
                observation(tic=888),
                observation(sector=106),
                observation(suffix="dvt.fits"),
                observation(suffix="s_tp.fits"),
                observation(suffix="dvr.pdf"),
                observation(suffix="dvr.xml"),
            ]
        )
        products = select_lightcurves(observations, {"42", "7"}, max_sector=105)
        self.assertEqual(len(products), 2)
        self.assertEqual({(str(p["tic_id"]), int(p["sector"])) for p in products}, {("42", 1), ("7", 2)})
        for product in products:
            self.assertEqual(float(product["cadence_seconds"]), 120.0)
            self.assertTrue(product["filename"].endswith("-s_lc.fits"))
            self.assertEqual(product["relative_path"], f"lightcurves/TIC{product['tic_id']}/{product['filename']}")
            self.assertEqual(product["data_uri"], f"mast:TESS/product/{product['filename']}")
            self.assertTrue(product["obs_id"])


class TessTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tess_download_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        filename = "tess2020000000000-s0001-0000000000000042-0001-s_lc.fits"
        self.product = {
            "tic_id": "42",
            "sector": 1,
            "cadence_seconds": 120.0,
            "obs_id": "tess2020000000000-s0001-0000000000000042-0001-s",
            "data_uri": f"mast:TESS/product/{filename}",
            "filename": filename,
            "relative_path": f"lightcurves/TIC42/{filename}",
        }
        self.destination = self.root / self.product["relative_path"]
        self.receipt = self.root / "metadata" / "receipts" / f"{filename}.json"
        self.payload = lightcurve_bytes()
        self.session = Mock()

    def test_streamed_fits_has_matching_receipt_and_is_reused_without_http(self):
        self.session.get.return_value = StreamResponse(self.payload)
        result = download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.destination.read_bytes(), self.payload)
        expected_hash = hashlib.sha256(self.payload).hexdigest()
        self.assertEqual(result["sha256"], expected_hash)
        self.assertEqual(result["size_bytes"], len(self.payload))
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt["data_uri"], self.product["data_uri"])
        self.assertEqual(receipt["sha256"], expected_hash)
        self.assertEqual(receipt["size_bytes"], len(self.payload))
        self.assertEqual(self.session.get.call_count, 1)

        resumed = download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertEqual(resumed["status"], "cached")
        self.assertEqual(self.session.get.call_count, 1)
        self.assertFalse(list(self.root.rglob("*.part")))

    def test_same_size_corruption_is_redownloaded(self):
        self.session.get.return_value = StreamResponse(self.payload)
        download_lightcurve(self.root, self.product, self.session, attempts=1)
        altered = bytearray(self.payload)
        altered[-2880] ^= 1  # Change table data while preserving file size and headers.
        self.destination.write_bytes(altered)
        self.assertEqual(self.destination.stat().st_size, len(self.payload))

        result = download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_missing_content_length_does_not_block_valid_fits(self):
        self.session.get.return_value = StreamResponse(self.payload, content_length=False)
        result = download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_truncated_or_wrong_identity_files_are_never_accepted(self):
        cases = {
            "incomplete FITS block": self.payload[:-1],
            "missing FITS data block": self.payload[:-2880],
            "wrong TIC": lightcurve_bytes(tic_id=999),
            "wrong sector": lightcurve_bytes(sector=2),
            "missing quality column": lightcurve_bytes(include_quality=False),
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                self.session.get.return_value = StreamResponse(payload)
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    download_lightcurve(self.root, self.product, self.session, attempts=1)
                self.assertFalse(self.destination.exists())
                self.assertFalse(self.receipt.exists())

    def test_mismatched_http_content_length_is_rejected_even_for_valid_fits(self):
        response = StreamResponse(self.payload)
        response.headers["Content-Length"] = str(len(self.payload) + 2880)
        self.session.get.return_value = response
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.receipt.exists())

    def test_spoc_checksum_without_datasum_preserves_bytes_and_rejects_corruption(self):
        # SPOC can include CHECKSUM without DATASUM. Astropy 6's direct
        # verify_checksum() mishandles this layout for HDUs with table data.
        output = io.BytesIO()
        with fits.open(io.BytesIO(self.payload), memmap=False) as hdus:
            for hdu in hdus:
                hdu.add_checksum(when="fixture checksum 2026-09-09", override_datasum=True)
            hdus.writeto(output)
        payload = output.getvalue()
        with fits.open(io.BytesIO(payload), memmap=False) as hdus:
            for hdu in hdus:
                self.assertIn("CHECKSUM", hdu.header)
                self.assertNotIn("DATASUM", hdu.header)
            table_offset = hdus[1].fileinfo()["datLoc"]

        self.session.get.return_value = StreamResponse(payload)
        result = download_lightcurve(self.root, self.product, self.session, attempts=1)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.destination.read_bytes(), payload)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())

        corrupted = bytearray(payload)
        corrupted[table_offset + 8] ^= 1  # First flux value; FITS structure stays intact.
        self.assertEqual(len(corrupted), len(payload))
        corrupt_root = self.root / "corrupt_source"
        self.session.get.return_value = StreamResponse(bytes(corrupted))
        with self.assertRaisesRegex(ValueError, "checksum"):
            download_lightcurve(corrupt_root, self.product, self.session, attempts=1)
        self.assertFalse((corrupt_root / self.product["relative_path"]).exists())
        self.assertFalse((corrupt_root / "metadata" / "receipts" / f"{self.product['filename']}.json").exists())

    def test_four_workers_overlap_and_preserve_serial_outputs(self):
        products, payloads = [], {}
        for tic in range(42, 46):
            product = dict(self.product)
            product["tic_id"] = str(tic)
            for key in ("obs_id", "filename", "data_uri", "relative_path"):
                product[key] = product[key].replace("0000000000000042", f"{tic:016d}").replace("TIC42", f"TIC{tic}")
            products.append(product)
            payloads[product["data_uri"]] = lightcurve_bytes(tic_id=tic)

        def session_factory(barrier=None):
            guard = threading.Lock()
            state = {"active": 0, "peak": 0, "created": 0, "closed": 0}

            class OverlappingResponse(StreamResponse):
                def iter_content(self, chunk_size=8192):
                    with guard:
                        state["active"] += 1
                        state["peak"] = max(state["peak"], state["active"])
                    try:
                        if barrier is not None:
                            # A serial implementation cannot pass this barrier.
                            barrier.wait(timeout=5)
                        yield from super().iter_content(chunk_size)
                    finally:
                        with guard:
                            state["active"] -= 1

            class Session:
                def __init__(self):
                    with guard:
                        state["created"] += 1

                def get(self, url, *, params, **kwargs):
                    return OverlappingResponse(payloads[params["uri"]])

                def close(self):
                    with guard:
                        state["closed"] += 1

            return Session, state

        serial_root, parallel_root = self.root / "serial", self.root / "parallel"
        serial_session, serial_state = session_factory()
        with patch("scripts.data.tess_download_raw.requests.Session", serial_session):
            self.assertEqual(run_downloads(serial_root, products, workers=1), 0)
        parallel_session, parallel_state = session_factory(threading.Barrier(4))
        with patch("scripts.data.tess_download_raw.requests.Session", parallel_session):
            self.assertEqual(run_downloads(parallel_root, products, workers=4), 0)

        self.assertEqual(serial_state, {"active": 0, "peak": 1, "created": 1, "closed": 1})
        self.assertEqual(parallel_state, {"active": 0, "peak": 4, "created": 4, "closed": 4})
        for product in products:
            relative_path = product["relative_path"]
            self.assertEqual((serial_root / relative_path).read_bytes(), payloads[product["data_uri"]])
            self.assertEqual((parallel_root / relative_path).read_bytes(), (serial_root / relative_path).read_bytes())
            receipt_path = Path("metadata") / "receipts" / f"{product['filename']}.json"
            serial_receipt = json.loads((serial_root / receipt_path).read_text())
            parallel_receipt = json.loads((parallel_root / receipt_path).read_text())
            self.assertEqual(serial_receipt["sha256"], parallel_receipt["sha256"])
            self.assertEqual(serial_receipt["size_bytes"], parallel_receipt["size_bytes"])
        for root in (serial_root, parallel_root):
            summary = json.loads((root / "metadata" / "download_summary.json").read_text())
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["downloaded_files"], 4)
            self.assertEqual(summary["failed_files"], 0)


class TessManifestTests(unittest.TestCase):
    def test_failed_query_does_not_publish_partial_manifest_and_can_resume(self):
        with tempfile.TemporaryDirectory(prefix="tess_manifest_test_") as temporary:
            metadata = Path(temporary)
            (metadata / "provenance.json").write_text("{}")
            targets = [str(tic) for tic in range(1, 102)]

            def observations(tic):
                obs_id = f"tess2020000000000-s0001-{tic:016d}-0001-s"
                return Table(rows=[{
                    "target_name": str(tic), "sequence_number": 1, "t_exptime": 120.0,
                    "provenance_name": "SPOC", "obs_collection": "TESS", "obs_id": obs_id,
                    "dataURL": f"mast:TESS/product/{obs_id}_lc.fits",
                }])

            with patch("scripts.data.tess_download_raw.Observations.query_criteria") as query:
                query.side_effect = [observations(1)] + [requests.ConnectionError("fixture outage")] * 3
                with patch("scripts.data.tess_download_raw.time.sleep"):
                    with self.assertRaises(requests.ConnectionError):
                        build_manifest(metadata, targets, max_sector=105)
                self.assertEqual(query.call_count, 4)
            self.assertFalse((metadata / "manifest.csv").exists())
            self.assertTrue((metadata / "mast_queries" / "observations_000000.ecsv").exists())
            self.assertFalse((metadata / "mast_queries" / "observations_000100.ecsv").exists())

            with patch("scripts.data.tess_download_raw.Observations.query_criteria") as query:
                query.return_value = observations(101)
                products = build_manifest(metadata, targets, max_sector=105)
                query.assert_called_once()
                self.assertEqual(query.call_args.kwargs["target_name"], ["101"])
            self.assertEqual({product["tic_id"] for product in products}, {"1", "101"})
            manifest = metadata / "manifest.csv"
            provenance = json.loads((metadata / "provenance.json").read_text())
            self.assertEqual(provenance["manifest_sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(len(provenance["mast_query_files"]), 2)
            with patch("scripts.data.tess_download_raw.Observations.query_criteria") as query:
                cached = build_manifest(metadata, targets, max_sector=105)
                query.assert_not_called()
            self.assertEqual([p["data_uri"] for p in cached], [p["data_uri"] for p in products])


if __name__ == "__main__":
    unittest.main()
