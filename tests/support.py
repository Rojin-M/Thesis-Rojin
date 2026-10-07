"""Shared synthetic fixtures for the active integration tests."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from astropy.io import fits

from scripts.research.protocol import utc_now


def curve(period=3.22, epoch=1501.1, depth=.01, duration=.12, seed=123):
    time = np.arange(1500, 1527, .02)
    flux = 1 + np.random.default_rng(seed).normal(0, .001, len(time))
    if depth:
        flux -= depth * (np.abs((time - epoch + .5 * period) % period - .5 * period) < duration / 2)
    return time, flux, np.full(len(time), .001)


def write_npz(path, value):
    time, flux, error = value
    np.savez(path, time=time, flux=flux, flux_err=error, quality=np.zeros(len(time), int))


def write_fits(path, mission="TESS", timezero=.125):
    time, flux, error = curve()
    quality = np.zeros(len(time), np.int32)
    quality[5] = 1
    if mission == "Kepler":
        time += 2457000 - 2454833
    time -= timezero
    names = ("TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", "QUALITY" if mission == "TESS" else "SAP_QUALITY")
    columns = [fits.Column(name=name, format="J" if name in ("QUALITY", "SAP_QUALITY") else "D", array=values)
               for name, values in zip(names, (time, flux, error, quality))]
    primary = fits.PrimaryHDU()
    primary.header["TICID" if mission == "TESS" else "KEPLERID"] = 123
    table = fits.BinTableHDU.from_columns(columns)
    table.header.update(TIMESYS="TDB", TIMEREF="SOLARSYSTEM", TIMEUNIT="d", BJDREFI=2457000 if mission == "TESS" else 2454833,
                        BJDREFF=0, TIMEZERO=timezero, TIMEDEL=.02)
    fits.HDUList([primary, table]).writeto(path, checksum=True)


class ReplayClient:
    def __init__(self, path=None, scenario="initial", size=None):
        self.path = path
        self.scenario = scenario
        self.size = size
        self.calls = []
        self.downloads = 0
        self.fail = False

    def query(self, request):
        self.calls.append(request)
        if self.fail:
            raise OSError("fixture simulated MAST outage")
        kind = "observations" if request["service"] == "Mast.Caom.Filtered" else "products"
        scenario = "initial" if self.scenario == "reprocessed" and kind == "observations" else self.scenario
        fixture = Path(__file__).parent / "fixtures" / "mast" / f"{kind}_{scenario}.json"
        value = json.loads(fixture.read_text())
        if kind == "products" and self.size:
            for row in value["data"]:
                row["size"] = self.size
        return json.dumps(value).encode()

    def download(self, product, path, pilot_id):
        self.downloads += 1
        if self.fail:
            raise OSError("fixture simulated download outage")
        raw = self.path.read_bytes()
        Path(path).write_bytes(raw)
        return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "source_uri": product["source_uri"], "retrieved_at": utc_now(), "fixture_only": True}