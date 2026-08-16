from __future__ import annotations

import json
import logging
import ssl
import time
from dataclasses import dataclass
from email.message import Message
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)


class HttpRequestError(RuntimeError):
    """Raised for transport failures and unexpected HTTP responses."""

    def __init__(self, message: str, *, status: int | None = None, body: bytes = b""):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpRequestError(
                "response is not valid UTF-8 JSON", status=self.status, body=self.body
            ) from exc


OpenUrl = Callable[[Request, float, ssl.SSLContext | None], Any]


def _default_open(
    request: Request, timeout: float, context: ssl.SSLContext | None
) -> Any:
    return urlopen(request, timeout=timeout, context=context)


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        default_headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 15,
        verify_tls: bool = True,
        user_agent: str = "mumu-autotask/0.1",
        opener: OpenUrl | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an http(s) URL")
        self.base_url = base_url.rstrip("/")
        self.default_headers = dict(default_headers or {})
        self.default_headers.setdefault("User-Agent", user_agent)
        self.timeout_seconds = timeout_seconds
        self._context = None if verify_tls else ssl._create_unverified_context()
        self._opener = opener or _default_open

    def _url(self, path: str, query: Mapping[str, Any] | None) -> str:
        path_parts = urlsplit(path)
        if path_parts.scheme or path_parts.netloc:
            raise HttpRequestError("endpoint path must be relative to base_url")
        url = self.base_url + "/" + path_parts.path.lstrip("/")
        parts = urlsplit(url)
        query_items: list[tuple[str, Any]] = list(parse_qsl(path_parts.query))
        for key, value in (query or {}).items():
            if isinstance(value, (list, tuple)):
                query_items.extend((key, item) for item in value)
            elif value is not None:
                query_items.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), ""))

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        form_body: Mapping[str, Any] | None = None,
        expected_status: tuple[int, ...] = (200,),
    ) -> HttpResponse:
        if json_body is not None and form_body is not None:
            raise ValueError("json_body and form_body are mutually exclusive")
        merged_headers = dict(self.default_headers)
        merged_headers.update(headers or {})
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            merged_headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif form_body is not None:
            body = urlencode(form_body, doseq=True).encode("utf-8")
            merged_headers.setdefault(
                "Content-Type", "application/x-www-form-urlencoded; charset=utf-8"
            )

        url = self._url(path, query)
        safe_url = urlunsplit((*urlsplit(url)[:3], "", ""))
        request = Request(url, data=body, headers=merged_headers, method=method.upper())
        started = time.monotonic()
        try:
            with self._opener(request, self.timeout_seconds, self._context) as raw:
                response_body = raw.read()
                response = HttpResponse(
                    status=raw.status,
                    headers=_headers_to_dict(raw.headers),
                    body=response_body,
                )
        except HTTPError as exc:
            response_body = exc.read()
            raise HttpRequestError(
                f"HTTP {exc.code} for {method.upper()} {safe_url}",
                status=exc.code,
                body=response_body,
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise HttpRequestError(
                f"transport failure for {method.upper()} {safe_url}: {exc}"
            ) from exc
        finally:
            LOGGER.info(
                "%s %s finished in %.3fs",
                method.upper(),
                safe_url,
                time.monotonic() - started,
            )

        if response.status not in expected_status:
            raise HttpRequestError(
                f"unexpected HTTP {response.status} for {method.upper()} {safe_url}",
                status=response.status,
                body=response.body,
            )
        return response


def _headers_to_dict(headers: Message | Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items()}
