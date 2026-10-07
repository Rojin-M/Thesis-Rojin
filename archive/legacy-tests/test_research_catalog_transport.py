"""Offline catalog transport framing, conservative charges and cumulative caps."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests
from urllib3.exceptions import ProtocolError

from scripts.research import registry_cache


class BoundedRaw(io.BytesIO):
    def __init__(self, payload, failure=None):
        super().__init__(payload)
        self.requests = []
        self.failure = failure

    def read(self, amount, decode_content=False):
        self.requests.append((amount, decode_content))
        if self.failure:
            raise self.failure
        return super().read(amount)


class CatalogResponse:
    def __init__(self, payload=b"", *, status=200, headers=None, failure=None):
        self.status_code = status
        self.headers = {"Content-Length": str(len(payload))} if headers is None else headers
        self.raw = BoundedRaw(payload, failure)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException("Fixture catalog HTTP " + str(self.status_code))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CatalogSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected extra catalog request")
        return self.responses.pop(0)


class CatalogTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.url = "https://example.invalid/catalog-fixture"
        self.client = registry_cache.BoundedCatalogClient(self.root)
        self.client.attempts = 1
        self.addCleanup(patch.stopall)
        patch.object(registry_cache, "MAX_RESPONSE", 8).start()
        patch.object(registry_cache, "MAX_REFRESH_BYTES", 16).start()
        patch.object(registry_cache.time, "sleep").start()
        patch("requests.sessions.Session.request", side_effect=AssertionError("No public network in catalog tests")).start()

    def attach(self, *responses):
        session = CatalogSession(responses)
        self.client.session = session
        return session

    def test_exact_remaining_reads_and_no_requests_after_total_cap(self):
        responses = [CatalogResponse(b"abcdef"), CatalogResponse(b"ghijkl"), CatalogResponse(b"mnop")]
        session = self.attach(*responses)
        for response in responses:
            received = self.client._request(self.url, headers={"If-None-Match": "fixture-etag"})
            self.assertEqual(received._content, response.raw.getvalue())
        self.assertEqual(self.client.downloaded_bytes, 16)
        self.assertEqual(self.client.known_read_bytes, 16)
        self.assertFalse(self.client.byte_counts_incomplete)
        self.assertEqual(responses[-1].raw.requests, [(4, False)])
        with self.assertRaisesRegex(requests.RequestException, "budget exhausted"):
            self.client._request(self.url)
        self.assertEqual(len(session.requests), 3)
        for _, options in session.requests:
            self.assertFalse(options["allow_redirects"])
            self.assertTrue(options["stream"])
            self.assertEqual(options["headers"]["Accept-Encoding"], "identity")
            self.assertEqual(options["headers"]["If-None-Match"], "fixture-etag")

    def test_unframed_full_response_never_reads_beyond_cap(self):
        response = CatalogResponse(b"abcdefghijkl", headers={})
        self.attach(response)
        with self.assertRaisesRegex(requests.RequestException, "Unframed"):
            self.client._request(self.url)
        self.assertEqual(response.raw.tell(), 8)
        self.assertEqual(response.raw.requests, [(8, False)])
        self.assertEqual(self.client.downloaded_bytes, 8)
        self.assertTrue(self.client.byte_counts_incomplete)

    def test_truncated_body_charges_entire_attempt_allowance(self):
        self.attach(CatalogResponse(b"abc", headers={"Content-Length": "6"}))
        with self.assertRaisesRegex(requests.RequestException, "Truncated"):
            self.client._request(self.url)
        self.assertEqual(self.client.downloaded_bytes, 8)
        self.assertEqual(self.client.known_read_bytes, 3)
        self.assertTrue(self.client.byte_counts_incomplete)
        self.assertEqual(self.client.transfer_receipts[0]["charged_bytes"], 8)
        self.assertEqual(self.client.transfer_receipts[0]["status"], "failed_conservative")

    def test_final_attempt_cap_uses_remaining_global_allowance(self):
        self.attach(CatalogResponse(b"abcdef"), CatalogResponse(b"ghijkl"),
                    CatalogResponse(b"abcde", headers={"Content-Length": "5"}))
        self.client._request(self.url)
        self.client._request(self.url)
        with self.assertRaisesRegex(requests.RequestException, "remaining cumulative"):
            self.client._request(self.url)
        self.assertEqual(self.client.downloaded_bytes, 16)
        self.assertEqual(self.client.transfer_receipts[-1]["attempt_cap_bytes"], 4)
        self.assertEqual(self.client.transfer_receipts[-1]["known_read_bytes"], 0)

    def test_redirects_and_compression_reject_without_following_or_reading(self):
        for response in (CatalogResponse(status=302, headers={"Location": "https://evil.invalid", "Content-Length": "0"}),
                         CatalogResponse(b"abc", headers={"Content-Length": "3", "Content-Encoding": "gzip"})):
            session = self.attach(response)
            with self.assertRaises(requests.RequestException):
                self.client._request(self.url)
            self.assertEqual(len(session.requests), 1)
            self.assertEqual(response.raw.requests, [])
        self.assertEqual(self.client.downloaded_bytes, 16)
        self.assertTrue(self.client.byte_counts_incomplete)

    def test_retries_are_charged_before_next_attempt(self):
        self.client.attempts = 2
        session = self.attach(CatalogResponse(status=503), CatalogResponse(b"abc"))
        result = self.client._request(self.url)
        self.assertEqual(result._content, b"abc")
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(self.client.downloaded_bytes, 11)
        self.assertEqual(self.client.known_read_bytes, 3)
        self.assertTrue(self.client.byte_counts_incomplete)
        self.assertEqual([receipt["status"] for receipt in self.client.transfer_receipts],
                         ["failed_conservative", "complete"])

    def test_interruption_charges_attempt_without_retrying(self):
        self.client.attempts = 2
        session = self.attach(CatalogResponse(b"abc", failure=TimeoutError("fixture outer deadline")))
        with self.assertRaisesRegex(TimeoutError, "outer deadline"):
            self.client._request(self.url)
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(self.client.downloaded_bytes, 8)
        self.assertTrue(self.client.byte_counts_incomplete)

    def test_raw_transport_errors_are_converted_and_conservatively_charged(self):
        for failure in (ProtocolError("fixture broken transport"), OSError("fixture disconnected socket")):
            with self.subTest(failure=type(failure).__name__):
                self.attach(CatalogResponse(b"abc", failure=failure))
                with self.assertRaises(requests.RequestException):
                    self.client._request(self.url)
        self.assertEqual(self.client.downloaded_bytes, 16)
        self.assertEqual(self.client.known_read_bytes, 0)
        self.assertTrue(self.client.byte_counts_incomplete)

    def test_empty_conditional_not_modified_response_uses_no_bytes(self):
        session = self.attach(CatalogResponse(status=304), CatalogResponse(status=304, headers={}),
                              CatalogResponse(status=304, headers={"Content-Length": "100", "Content-Encoding": "gzip"}))
        for _ in range(3):
            response = self.client._request(self.url, headers={"If-None-Match": "fixture"})
            self.assertEqual(response.status_code, 304)
            self.assertEqual(response._content, b"")
            self.assertEqual(response.raw.requests, [])
        self.assertEqual(len(session.requests), 3)
        self.assertEqual(self.client.downloaded_bytes, 0)
        self.assertFalse(self.client.byte_counts_incomplete)

    def test_bundle_exposes_unknown_bytes_and_conservative_source_receipts(self):
        def unavailable(client, tic):
            client.attempts = 1
            client.session = CatalogSession([CatalogResponse(status=503)])
            try:
                client._request(self.url)
            except requests.RequestException:
                pass
            return []

        with patch.object(registry_cache.BoundedCatalogClient, "lookup", unavailable):
            bundle = registry_cache.fetch_bundle(self.root / "bundles", "123", "live")
        self.assertIsNone(bundle["downloaded_bytes_this_call"])
        self.assertTrue(bundle["byte_counts_incomplete"])
        self.assertEqual(bundle["downloaded_bytes"], 8)
        self.assertEqual(bundle["known_read_bytes"], 0)
        self.assertEqual(bundle["download_receipts"][0]["url"], self.url)
        self.assertEqual(bundle["download_receipts"][0]["charged_bytes"], 8)
        saved = json.loads((self.root / "bundles" / "tic-123.json").read_text())["bundle"]
        self.assertEqual(saved["download_receipts"], bundle["download_receipts"])


if __name__ == "__main__":
    unittest.main()
