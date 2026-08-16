from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass
from typing import Any, Mapping

from .config import EndpointSpec, WorkflowSpec
from .http import HttpClient, HttpResponse


LOGGER = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    """Raised when a configured workflow cannot be rendered or completed."""


@dataclass(frozen=True, slots=True)
class StepResult:
    action: str
    status: int
    extracted: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    name: str
    serial: str
    context: Mapping[str, Any]
    steps: tuple[StepResult, ...]


_EXACT_FIELD = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class _StrictFormatMap(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise WorkflowError(f"template variable {key!r} is not available")


def render(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        exact = _EXACT_FIELD.fullmatch(value)
        if exact:
            key = exact.group(1)
            if key not in context:
                raise WorkflowError(f"template variable {key!r} is not available")
            return context[key]
        try:
            return string.Formatter().vformat(value, (), _StrictFormatMap(context))
        except (KeyError, AttributeError, IndexError, ValueError) as exc:
            raise WorkflowError(f"cannot render template {value!r}: {exc}") from exc
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(render(item, context) for item in value)
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    return value


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise WorkflowError(f"JSON Pointer must start with '/': {pointer!r}")
    current = document
    for encoded_token in pointer[1:].split("/"):
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise TypeError(type(current).__name__)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise WorkflowError(
                f"JSON Pointer {pointer!r} cannot resolve token {token!r}"
            ) from exc
    return current


class WorkflowRunner:
    def __init__(
        self,
        endpoints: Mapping[str, EndpointSpec],
        client: HttpClient,
    ) -> None:
        self.endpoints = endpoints
        self.client = client

    def run(
        self,
        name: str,
        workflow: WorkflowSpec,
        *,
        serial: str,
        variables: Mapping[str, Any] | None = None,
    ) -> WorkflowResult:
        context: dict[str, Any] = {"serial": serial}
        context.update(variables or {})
        results: list[StepResult] = []

        for step in workflow.steps:
            endpoint = self.endpoints.get(step.action)
            if endpoint is None:
                raise WorkflowError(f"endpoint {step.action!r} is not configured")
            if not endpoint.enabled:
                raise WorkflowError(f"endpoint {step.action!r} is disabled")

            rendered_inputs = render(step.inputs, context)
            context.update(rendered_inputs)
            LOGGER.info(
                "running workflow step",
                extra={"workflow": name, "action": step.action, "serial": serial},
            )
            response = self._request(endpoint, context)
            extracted = self._extract(response, step.extract)
            context.update(extracted)
            results.append(StepResult(step.action, response.status, extracted))

        return WorkflowResult(name, serial, dict(context), tuple(results))

    def _request(self, endpoint: EndpointSpec, context: Mapping[str, Any]) -> HttpResponse:
        return self.client.request(
            endpoint.method,
            str(render(endpoint.path, context)),
            headers=render(endpoint.headers, context),
            query=render(endpoint.query, context),
            json_body=render(endpoint.json_body, context),
            form_body=render(endpoint.form_body, context),
            expected_status=endpoint.expected_status,
        )

    @staticmethod
    def _extract(response: HttpResponse, pointers: Mapping[str, str]) -> dict[str, Any]:
        if not pointers:
            return {}
        document = response.json()
        return {
            variable: resolve_json_pointer(document, pointer)
            for variable, pointer in pointers.items()
        }

