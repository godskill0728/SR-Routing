"""Offline package tests; COMPARE_STAGE points at the portable Portal modules."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from email.message import Message
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, os.environ["COMPARE_STAGE"])
import compare_release as app


def document(mode="on"):
    tid = "a" * 32
    def span(sid, name, start, duration, parent=None):
        return {"spanID": sid, "operationName": "semantic_router." + name,
                "startTime": start, "duration": duration, "processID": "p1",
                "references": [] if parent is None else [{"refType": "CHILD_OF", "spanID": parent, "traceID": tid}]}
    return {"data": [{"traceID": tid, "processes": {"p1": {"serviceName": "sr-demo-" + mode}},
        "spans": [span("s", "signal.evaluation", 10000, 4000), span("d", "decision.evaluation", 14010, 50, "s"),
                  span("u", "upstream.request", 15000, 500000, "d")]}]}


class TimingTest(unittest.TestCase):
    def test_exact_span_units_and_interval_not_llm(self):
        for mode in ("on", "off"):
            result = app.trace_timing(document(mode), "a" * 32, mode)
            self.assertEqual(result["signal_seconds"], .004)
            self.assertEqual(result["routing_stage_seconds"], .005)

    def test_reject_wrong_trace_service_and_partial_export(self):
        self.assertIsNone(app.trace_timing(document(), "b" * 32, "on"))
        self.assertIsNone(app.trace_timing(document(), "a" * 32, "off"))
        self.assertIsNone(app.trace_timing(document("off"), "a" * 32, "on"))
        with patch.dict(os.environ, {"TRACE_SERVICE_ON": "custom-on"}):
            self.assertIsNone(app.trace_timing(document(), "a" * 32, "on"))
            custom = document()
            custom["data"][0]["processes"]["p1"]["serviceName"] = "custom-on"
            self.assertIsNotNone(app.trace_timing(custom, "a" * 32, "on"))
        doc = document(); doc["data"][0]["spans"].pop()
        self.assertIsNone(app.trace_timing(doc, "a" * 32, "on"))

    def test_reject_ambiguous_duplicate_signal(self):
        doc = document(); doc["data"][0]["spans"].append(copy.deepcopy(doc["data"][0]["spans"][0]))
        self.assertIsNone(app.trace_timing(doc, "a" * 32, "on"))

    def test_reject_unrelated_branch_and_invalid_timestamps(self):
        doc = document(); doc["data"][0]["spans"][-1]["references"] = []
        self.assertIsNone(app.trace_timing(doc, "a" * 32, "on"))
        for val in (-1, "100", True, 20000):
            doc = document(); doc["data"][0]["spans"][0]["duration"] = val
            self.assertIsNone(app.trace_timing(doc, "a" * 32, "on"))


class FakeResponse(io.BytesIO):
    def __init__(self):
        super().__init__(b'data: {"model":"gemma-4-12B","choices":[{"delta":{"content":"test"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        self.headers = Message()
        self.headers["x-vsr-selected-model"] = "gemma-4-12b"


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.portal.ThreadingHTTPServer(("127.0.0.1", 0), app.CompareHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        with app.LOCK:
            app.RUNS.clear()
        self.body = {"prompt": "same prompt", "amx_mode": "on", "max_tokens": 128}

    def request(self, route="/api/compare/stream", body=None, headers=None):
        req = urllib.request.Request(self.base + route, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers or {"Content-Type": "application/json"})
        try:
            resp = self.client.open(req, timeout=4)
        except urllib.error.HTTPError as exc:
            resp = exc
        with resp:
            return resp.status, resp.read(), resp.headers

    def test_static_navigation_no_inference(self):
        with patch.object(app.portal.INTERNAL_HTTP, "open") as call:
            self.assertIn(b'href="/compare/"', self.request("/")[1])
            self.assertEqual(self.request("/compare/")[0], 200)
            self.assertEqual(self.request("/compare/demo.js")[0], 200)
            self.assertEqual(self.request("/compare/../compare_release.py")[0], 404)
            call.assert_not_called()

    def test_each_mode_one_call_same_parameters_unique_trace(self):
        with patch.object(app.portal.INTERNAL_HTTP, "open", side_effect=lambda *a, **k: FakeResponse()) as call:
            for mode in ("on", "off"):
                self.body["amx_mode"] = mode
                status, data, _ = self.request(body=self.body)
                self.assertEqual(status, 200)
                self.assertIn(b"event: done", data)
                self.assertIn(b"event: target", data)
            self.assertEqual(call.call_count, 2)
            requests = [c.args[0] for c in call.call_args_list]
            self.assertEqual(requests[0].data, requests[1].data)
            self.assertNotEqual(requests[0].get_header("Traceparent"), requests[1].get_header("Traceparent"))
            for mode, req in zip(("on", "off"), requests):
                self.assertEqual(req.full_url, app.portal.CHAT_TARGETS[mode] + "/v1/chat/completions")
                self.assertEqual(json.loads(req.data)["max_tokens"], 128)

    def test_invalid_inputs_do_not_infer(self):
        with patch.object(app.portal.INTERNAL_HTTP, "open") as call:
            for key, value in (("amx_mode", "http://evil/"), ("prompt", ""), ("max_tokens", True), ("max_tokens", 1025)):
                body = {**self.body, key: value}
                self.assertEqual(self.request(body=body)[0], 400)
            self.assertEqual(self.request(body={**self.body, "url": "http://evil/"})[0], 400)
            self.assertEqual(self.request(body=self.body, headers={"Content-Type": "application/json", "Origin": "http://evil"})[0], 403)
            self.assertEqual(self.request(body=self.body, headers={"Content-Type": "text/plain"})[0], 415)
            call.assert_not_called()

    def test_busy_and_capacity_do_not_open_stream(self):
        for _ in range(4): app.SLOTS.acquire()
        try:
            self.assertEqual(self.request(body=self.body)[0], 429)
        finally:
            for _ in range(4): app.SLOTS.release()
        with patch.object(app, "register_run", return_value=None):
            status, data, _ = self.request(body=self.body)
            self.assertEqual(status, 429)
            self.assertNotIn(b"event:", data)

    def test_upstream_failure_no_retry_or_error_detail_leak(self):
        with patch.object(app.portal.INTERNAL_HTTP, "open", side_effect=RuntimeError("private upstream detail")) as call:
            status, data, _ = self.request(body=self.body)
            self.assertEqual(status, 200)
            self.assertIn(b"event: error", data)
            self.assertNotIn(b"private upstream", data)
            self.assertEqual(call.call_count, 1)

    def test_timing_only_known_capabilities_pending_not_zero(self):
        with patch.object(app.portal.INTERNAL_HTTP, "open", side_effect=RuntimeError("unavailable")) as call:
            self.assertEqual(self.request("/api/compare/timing/" + "a" * 32)[0], 404)
            call.assert_not_called()
            token, entry = app.register_run("on")
            status, data, _ = self.request("/api/compare/timing/" + token)
            self.assertEqual(json.loads(data), {"state": "pending"})
            self.request("/api/compare/timing/" + token)
            self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()