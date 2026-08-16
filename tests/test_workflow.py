from __future__ import annotations

import json
import unittest

from mumu_autotask.config import EndpointSpec, WorkflowSpec, WorkflowStep
from mumu_autotask.http import HttpResponse
from mumu_autotask.workflow import WorkflowError, WorkflowRunner


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/lookup":
            body = json.dumps({"data": {"target": {"id": 42}}}).encode()
        else:
            body = b'{"ok":true}'
        return HttpResponse(200, {}, body)


class WorkflowTests(unittest.TestCase):
    def test_extracts_response_value_for_next_post(self) -> None:
        endpoints = {
            "lookup": EndpointSpec("POST", "/lookup", json_body={"color": "{color}"}),
            "march": EndpointSpec("POST", "/march", json_body={"target": "{target_id}"}),
        }
        workflow = WorkflowSpec(
            (
                WorkflowStep("lookup", extract={"target_id": "/data/target/id"}),
                WorkflowStep("march"),
            )
        )
        client = FakeHttpClient()
        result = WorkflowRunner(endpoints, client).run(
            "attack", workflow, serial="device-1", variables={"color": "purple"}
        )
        self.assertEqual(result.context["target_id"], 42)
        self.assertEqual(client.calls[1][2]["json_body"], {"target": 42})

    def test_missing_template_variable_fails_before_request(self) -> None:
        endpoint = EndpointSpec("POST", "/march", json_body={"target": "{target_id}"})
        client = FakeHttpClient()
        with self.assertRaisesRegex(WorkflowError, "target_id"):
            WorkflowRunner({"march": endpoint}, client).run(
                "attack", WorkflowSpec((WorkflowStep("march"),)), serial="device-1"
            )
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
