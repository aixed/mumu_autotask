from __future__ import annotations

import json
import unittest
from email.message import Message

from mumu_autotask.http import HttpClient, HttpRequestError


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class HttpTests(unittest.TestCase):
    def test_posts_json_and_query_without_retry(self) -> None:
        calls = []

        def opener(request, timeout, context):
            calls.append((request, timeout, context))
            return FakeResponse(body=b'{"ok":true}')

        client = HttpClient("https://example.test/api", opener=opener)
        response = client.request(
            "POST",
            "/captured",
            query={"account": 7},
            json_body={"color": "purple"},
        )
        self.assertTrue(response.json()["ok"])
        self.assertEqual(len(calls), 1)
        request = calls[0][0]
        self.assertEqual(request.full_url, "https://example.test/api/captured?account=7")
        self.assertEqual(json.loads(request.data), {"color": "purple"})

    def test_rejects_absolute_endpoint(self) -> None:
        client = HttpClient("https://example.test", opener=lambda *args: FakeResponse())
        with self.assertRaisesRegex(HttpRequestError, "relative"):
            client.request("POST", "https://other.test/action")

    def test_error_does_not_expose_query_values(self) -> None:
        client = HttpClient(
            "https://example.test", opener=lambda *args: FakeResponse(status=500)
        )
        with self.assertRaises(HttpRequestError) as raised:
            client.request("POST", "/action", query={"token": "secret-value"})
        self.assertNotIn("secret-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
