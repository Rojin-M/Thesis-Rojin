"""Offline public MAST download redirects retain strict scope and byte receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.research import mast
from scripts.research.protocol import ValidationError
from scripts.research.store import Store
from scripts.research.watcher_store import WatchStore, status
from tests.test_research_detection import write_fits
from tests.test_research_watcher import FIXTURES, FakeResponse


class ResponseSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, deepcopy(kwargs)))
        if not self.responses:
            raise AssertionError("Unexpected additional archive request")
        return self.responses.pop(0)


class MastDownloadRedirectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "fixture.fits"
        write_fits(self.source)
        self.payload = self.source.read_bytes()
        self.size = len(self.payload)
        self.store = Store(self.root / "research.sqlite3").initialize()
        self.ledger = WatchStore(self.store)
        fixture = json.loads((FIXTURES / "products_initial.json").read_text())["data"][0]
        self.product = {"source_uri": fixture["dataURI"], "metadata": {"size_bytes": self.size}}
        self.expected_url = ("https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/"
                             "s0001/0000/0000/0000/0123/" + fixture["productFilename"])
        self.block_network = patch("requests.sessions.Session.request",
                                   side_effect=AssertionError("Public network forbidden in redirect replay"))
        self.block_network.start()
        self.addCleanup(self.block_network.stop)

    def redirect(self, url=None, **headers):
        return FakeResponse(b"", {"Content-Length": "0", "Location": url or self.expected_url, **headers}, status=302)

    def client(self, responses):
        session = ResponseSession(responses)
        return mast.MastClient(self.ledger, session=session), session

    def test_valid_cloud_redirect_preserves_download_bytes_and_source(self):
        client, session = self.client([self.redirect(), FakeResponse(self.payload, {
            "Content-Length": str(self.size), "ETag": "fixture-etag", "Last-Modified": "fixture-timestamp",
        })])
        destination = self.root / "download.fits"
        receipt = client.download(self.product, destination, None)
        self.assertEqual(mast.public_product_url(self.product["source_uri"]), self.expected_url)
        self.assertEqual(destination.read_bytes(), self.payload)
        self.assertEqual(receipt["bytes"], self.size)
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(receipt["source_uri"], self.product["source_uri"])
        self.assertEqual(receipt["url"], self.expected_url)
        self.assertEqual(receipt["requested_url"], mast.DOWNLOAD)
        self.assertEqual(receipt["redirects"], [{"url": mast.DOWNLOAD, "status": 302, "location": self.expected_url}])
        self.assertEqual(receipt["etag"], "fixture-etag")
        self.assertEqual(receipt["last_modified"], "fixture-timestamp")
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(session.requests[0][:2], ("GET", mast.DOWNLOAD))
        self.assertEqual(session.requests[0][2]["params"], {"uri": self.product["source_uri"]})
        self.assertEqual(session.requests[1][:2], ("GET", self.expected_url))
        self.assertNotIn("params", session.requests[1][2])
        self.assertNotIn("data", session.requests[1][2])
        self.assertTrue(all(request[2]["allow_redirects"] is False for request in session.requests))
        budget = status(self.store)["budget"]
        self.assertEqual(budget["charged_bytes"], self.size)
        self.assertEqual(budget["unsettled_reservations"], 0)
        with self.store.connection() as database:
            spending = database.execute("SELECT count(*) FROM watch_spending").fetchone()[0]
        self.assertEqual(spending, 1)

    def test_untrusted_or_mismatched_cloud_locations_never_receive_a_request(self):
        invalid_urls = [
            self.expected_url.replace("stpubdata.s3.us-east-1.amazonaws.com", "evil.example"),
            self.expected_url.replace("/s0001/", "/s0002/"),
            self.expected_url.replace("/0123/", "/0124/"),
            self.expected_url.replace("-0120-s_lc.fits", "-0121-s_lc.fits"),
            self.expected_url + "?download=1",
            self.expected_url + "#fragment",
            self.expected_url.replace("https://", "http://"),
            self.expected_url.replace("https://", "https://user@"),
            self.expected_url.replace("amazonaws.com/", "amazonaws.com:443/"),
        ]
        for number, invalid_url in enumerate(invalid_urls):
            with self.subTest(location=invalid_url):
                client, session = self.client([self.redirect(invalid_url)])
                with self.assertRaises((OSError, ValidationError)):
                    client.download(self.product, self.root / ("rejected-" + str(number) + ".fits"), None)
                self.assertEqual(len(session.requests), 1)
        self.assertEqual(status(self.store)["budget"]["charged_bytes"], self.size * len(invalid_urls))
        self.assertEqual(status(self.store)["budget"]["unsettled_reservations"], 0)

    def test_only_empty_framed_uncompressed_redirects_are_followed(self):
        headers = [
            {"Content-Length": "1", "Location": self.expected_url},
            {"Location": self.expected_url},
            {"Content-Length": "0", "Location": self.expected_url, "Content-Encoding": "gzip"},
            {"Content-Length": "0", "Location": self.expected_url, "Transfer-Encoding": "chunked"},
            {"Content-Length": "0"},
        ]
        for number, response_headers in enumerate(headers):
            with self.subTest(headers=response_headers):
                client, session = self.client([FakeResponse(b"x" if number == 0 else b"", response_headers, status=302)])
                with self.assertRaises((OSError, ValidationError)):
                    client.download(self.product, self.root / ("unframed-" + str(number) + ".fits"), None)
                self.assertEqual(len(session.requests), 1)
        self.assertEqual(status(self.store)["budget"]["charged_bytes"], self.size * len(headers))

    def test_second_redirect_is_rejected_without_third_request(self):
        client, session = self.client([self.redirect(), self.redirect()])
        with self.assertRaises((OSError, ValidationError)):
            client.download(self.product, self.root / "chained.fits", None)
        self.assertEqual(len(session.requests), 2)
        budget = status(self.store)["budget"]
        self.assertEqual(budget["charged_bytes"], self.size)
        self.assertEqual(budget["unsettled_reservations"], 0)

    def test_truncated_final_product_charges_full_reservation(self):
        for number, declared_size in enumerate((self.size, self.size // 2)):
            with self.subTest(content_length=declared_size):
                client, session = self.client([self.redirect(), FakeResponse(self.payload[:self.size // 2],
                                                       {"Content-Length": str(declared_size)})])
                with self.assertRaises((OSError, ValidationError)):
                    client.download(self.product, self.root / ("truncated-" + str(number) + ".fits"), None)
                self.assertEqual(len(session.requests), 2)
        budget = status(self.store)["budget"]
        self.assertEqual(budget["charged_bytes"], 2 * self.size)
        self.assertEqual(budget["unsettled_reservations"], 0)

    def test_metadata_and_generic_transfers_do_not_follow_redirects(self):
        client, session = self.client([self.redirect()])
        with self.assertRaises(OSError):
            client.query({"service": "fixture-metadata-only"})
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(session.requests[0][0], "POST")
        client, session = self.client([self.redirect()])
        with self.assertRaises(OSError):
            client._transfer("GET", mast.DOWNLOAD, self.size, path=self.root / "generic.fits")
        self.assertEqual(len(session.requests), 1)

    def test_redirect_permission_requires_official_get_download_endpoint(self):
        for number, (method, endpoint) in enumerate((("POST", mast.INVOKE), ("GET", "https://example.test/download"))):
            with self.subTest(method=method, endpoint=endpoint):
                client, session = self.client([self.redirect()])
                with self.assertRaises((OSError, ValidationError)):
                    client._transfer(method, endpoint, self.size, path=self.root / ("wrong-origin-" + str(number) + ".fits"),
                                     redirect_url=self.expected_url)
                self.assertLessEqual(len(session.requests), 1)

    def test_direct_download_remains_supported(self):
        client, session = self.client([FakeResponse(self.payload)])
        receipt = client.download(self.product, self.root / "direct.fits", None)
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(receipt["url"], mast.DOWNLOAD)
        self.assertEqual(receipt["source_uri"], self.product["source_uri"])
        self.assertEqual(status(self.store)["budget"]["charged_bytes"], self.size)

    def test_cloud_location_is_derived_from_sector_and_all_tic_groups(self):
        filename = "tess2025258001959-s0097-0000000150428135-0294-s_lc.fits"
        expected = "https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/s0097/0000/0001/5042/8135/" + filename
        self.assertEqual(mast.public_product_url("mast:TESS/product/" + filename), expected)

    def test_interrupted_cloud_stream_retains_retryable_failure_and_full_charge(self):
        from urllib3.exceptions import ProtocolError
        from scripts.research.watcher import _error
        response = FakeResponse(self.payload)
        client, session = self.client([self.redirect(), response])
        with patch.object(response.raw, 'read', side_effect=ProtocolError('Fixture broken connection')):
            with self.assertRaises(OSError) as caught:
                client.download(self.product, self.root / 'broken.fits', None)
        self.assertTrue(_error(caught.exception)['retryable'])
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(status(self.store)['budget']['charged_bytes'], self.size)
        self.assertEqual(status(self.store)['budget']['unsettled_reservations'], 0)


if __name__ == "__main__":
    unittest.main()
