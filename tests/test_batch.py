"""Offline tests only: no production evals. BATCH_STAGE is the prepared source snapshot."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, os.environ["BATCH_STAGE"])
import batch_release as app

CORPUS_ROOT = Path(__file__).resolve().parent.parent / "reports-public"
DATA = json.loads((CORPUS_ROOT / "corpus.json").read_text())


def good(mode="on"):
    return {"outcome": "ok", "error": None, "http_status": 200, "complexity_seconds": .01 if mode == "on" else .02,
            "http_seconds": .03 if mode == "on" else .06, "decision": "route-medium",
            "models": ["gemma-4-12b"], "complexity": ["task-complexity:medium"]}


def job(rounds=1):
    now = time.monotonic()
    return {"run_id": "a" * 32, "rounds": rounds, "state": "warming", "reason": None, "rows": [],
            "created_utc": "2026-10-14T00:00:00Z", "started_mono": now, "heartbeat": now,
            "cancel": threading.Event(), "current": None, "protocol": app.protocol(rounds)}


class BatchTest(unittest.TestCase):
    def setUp(self):
        app.JOBS.clear()
        app.single.SLOTS = threading.BoundedSemaphore(4)

    def run_job(self, j, evaluate=None):
        for _ in range(4): app.single.SLOTS.acquire()
        with patch.object(app, "evaluate", side_effect=evaluate or (lambda mode, prompt: good(mode))) as mock:
            app.worker(j, DATA)
        for _ in range(4): self.assertTrue(app.single.SLOTS.acquire(blocking=False))
        self.assertFalse(app.single.SLOTS.acquire(blocking=False))
        for _ in range(4): app.single.SLOTS.release()
        return mock

    def test_corpus_pin_and_original_warmups(self):
        with patch.object(app.portal, "REPORTS_ROOT", CORPUS_ROOT):
            self.assertEqual(len(app.corpus()["prompts"]), 100)
        with patch.object(app.portal, "REPORTS_ROOT", CORPUS_ROOT), patch.object(app, "CORPUS_SHA", "wrong"):
            with self.assertRaises(ValueError): app.corpus()

    def test_reproducible_balanced_paired_schedule(self):
        schedule = list(app.schedule(DATA, 3))
        self.assertEqual(schedule, list(app.schedule(DATA, 3)))
        self.assertEqual(len(schedule), 632)
        for number in range(1,4):
            rows = [r for r in schedule if r[1] == number]
            self.assertEqual(len(rows), 200)
            for i in range(0,200,2):
                self.assertEqual(rows[i][5], rows[i+1][5])
                self.assertEqual({rows[i][4],rows[i+1][4]}, {"on","off"})
            self.assertEqual(sum(r[4]=="on" for r in rows if r[3]==0), 50)
            self.assertEqual(len({r[5]["id"] for r in rows}), 100)
        self.assertNotEqual([r[5]["id"] for r in schedule if r[1]==1], [r[5]["id"] for r in schedule if r[1]==2])

    def test_full_three_round_statistics_excludes_warmups(self):
        j = job(3); mock = self.run_job(j)
        self.assertEqual(mock.call_count,632)
        self.assertEqual(j["state"],"completed")
        summary = app.aggregate(j["rows"],3)
        self.assertEqual(summary["successful_pairs"],300)
        self.assertEqual(summary["measured_attempts"],600)
        self.assertEqual(summary["modes"]["on"]["complexity_seconds"]["n"],300)
        self.assertAlmostEqual(summary["ratios"]["complexity_seconds"]["ratio_of_means_off_on"],2)
        self.assertEqual(summary["agreement"]["decision"],300)
        self.assertEqual(summary["by_round"][2]["successful_pairs"],100)

    def test_empty_statistics_never_zero(self):
        s = app.aggregate([],3)
        self.assertIsNone(s["ratios"]["complexity_seconds"]["ratio_of_means_off_on"])
        self.assertIsNone(s["modes"]["on"]["http_seconds"]["mean"])
        self.assertEqual(s["unattempted_pairs"],300)

    def test_warmup_failure_stops_no_formal_requests(self):
        j=job(); self.run_job(j, lambda mode,prompt:{**good(mode),"outcome":"error","error":"timeout","complexity_seconds":None})
        self.assertEqual(len(j["rows"]),1)
        self.assertEqual(j["reason"],"warmup_failed")
        self.assertEqual(app.aggregate(j["rows"],1)["warmup_failures"],1)

    def test_three_formal_failures_stop_without_retry(self):
        j=job()
        def evaluate(mode,prompt):
            if len(j["rows"]) < 32:return good(mode)
            return {**good(mode),"outcome":"error","error":"invalid_eval_response","complexity_seconds":None}
        self.run_job(j,evaluate)
        self.assertEqual(len(j["rows"]),35)
        self.assertEqual(j["reason"],"three_consecutive_failures")
        s=app.aggregate(j["rows"],1)
        self.assertEqual(s["incomplete_or_failed_pairs"],2)
        self.assertEqual(s["unattempted_pairs"],98)
        self.assertEqual(s["successful_pairs"],0)

    def test_isolated_failure_and_disagreement_retained(self):
        j=job()
        def evaluate(mode,prompt):
            if len(j["rows"])==32:return {**good(mode),"outcome":"error","error":"timeout","complexity_seconds":None}
            if mode=="off":return {**good(mode),"decision":"route-hard","models":["other"],"complexity":["hard"]}
            return good(mode)
        self.run_job(j,evaluate);s=app.aggregate(j["rows"],1)
        self.assertEqual(j["state"],"completed_with_errors")
        self.assertEqual(s["successful_pairs"],99)
        self.assertEqual(s["agreement"]["models"],0)
        self.assertEqual(s["incomplete_or_failed_pairs"],1)

    def test_cancel_and_lease_stop_between_requests(self):
        j=job()
        def evaluate(mode,prompt):j["cancel"].set();return good(mode)
        self.run_job(j,evaluate)
        self.assertEqual(len(j["rows"]),1);self.assertEqual(j["reason"],"user_cancelled")
        j=job();j["heartbeat"]-=46
        mock=self.run_job(j)
        mock.assert_not_called();self.assertEqual(j["reason"],"browser_lease_expired")

    def test_wall_limit_and_worker_exception_release_slots(self):
        j=job();j["started_mono"]-=1201
        self.run_job(j);self.assertEqual(j["reason"],"wall_time_limit")
        j=job()
        def evaluate(mode,prompt):raise RuntimeError("private detail")
        self.run_job(j,evaluate);self.assertEqual(j["reason"],"internal_worker_error")

    def test_idempotent_start_and_batch_single_exclusion(self):
        with patch.object(app,"corpus",return_value=DATA), patch.object(app.threading,"Thread") as thread:
            code,_=app.start_job("a"*32,1);self.assertEqual(code,202)
            self.assertEqual(app.start_job("a"*32,1)[0],200)
            self.assertEqual(app.start_job("a"*32,3)[0],409)
            self.assertEqual(app.start_job("b"*32,1)[0],409)
            self.assertEqual(thread.call_count,1)
            self.assertFalse(app.single.SLOTS.acquire(blocking=False))

    def test_busy_or_bad_corpus_creates_no_worker(self):
        with patch.object(app.threading,"Thread") as thread:
            app.single.SLOTS.acquire()
            self.assertEqual(app.start_job("a"*32,1)[0],409)
            app.single.SLOTS.release()
            with patch.object(app,"corpus",side_effect=ValueError("changed")):
                self.assertEqual(app.start_job("a"*32,1)[0],503)
            thread.assert_not_called()
        self.assertEqual(app.JOBS,{})

    def test_snapshot_no_private_fields_and_unknown_run(self):
        self.assertIsNone(app.snapshot("f"*32))
        j=job();app.JOBS[j["run_id"]]=j
        s=app.snapshot(j["run_id"])
        self.assertNotIn("cancel",s);self.assertNotIn("heartbeat",s)
        json.dumps(s,allow_nan=False)


class EvalTest(unittest.TestCase):
    def response(self,body):
        response=io.BytesIO(json.dumps(body).encode());response.status=200;return response

    def data(self):
        return {"original_text":"test prompt","metrics":{"complexity":{"execution_time_ms":25}},
                "routing_decision":"route-medium","recommended_models":["gemma-4-12b"],
                "decision_result":{"matched_signals":{"complexity":["task-complexity:medium"]}}}

    def test_exact_fixed_eval_payload_no_gpu(self):
        with patch.object(app.portal.INTERNAL_HTTP,"open",side_effect=lambda *a,**k:self.response(self.data())) as call:
            for mode in ("on","off"):
                row=app.evaluate(mode,{"text":"test prompt"})
                self.assertEqual(row["outcome"],"ok");self.assertEqual(row["complexity_seconds"],.025)
            self.assertEqual(call.call_count,2)
            for mode,c in zip(("on","off"),call.call_args_list):
                self.assertEqual(c.args[0].full_url,app.EVAL_URLS[mode])
                self.assertEqual(json.loads(c.args[0].data),{"text":"test prompt"})

    def test_invalid_missing_zero_nan_metric_not_success(self):
        for value in (None,0,-1,True,"25",float("nan")):
            data=self.data();data["metrics"]["complexity"]["execution_time_ms"]=value
            with patch.object(app.portal.INTERNAL_HTTP,"open",return_value=self.response(data)):
                row=app.evaluate("on",{"text":"test prompt"})
                self.assertEqual(row["error"],"invalid_eval_response")
                self.assertIsNone(row["complexity_seconds"])

    def test_error_no_retry_or_secret_echo(self):
        with patch.object(app.portal.INTERNAL_HTTP,"open",side_effect=urllib.error.URLError("private-address")) as call:
            row=app.evaluate("on",{"text":"test prompt"})
            self.assertEqual(call.call_count,1);self.assertEqual(row["error"],"transport_error")
            self.assertNotIn("private-address",json.dumps(row))


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.portal.ThreadingHTTPServer(("127.0.0.1",0),app.BatchHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base="http://127.0.0.1:"+str(cls.server.server_port)
        cls.client=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=headers or {"Content-Type":"application/json"})
        try:r=self.client.open(req,timeout=5)
        except urllib.error.HTTPError as exc:r=exc
        with r:return r.status,r.read()

    def test_pages_info_only_no_evaluation(self):
        with patch.object(app.portal,"REPORTS_ROOT",CORPUS_ROOT),patch.object(app.portal.INTERNAL_HTTP,"open") as call:
            for path in ("/compare/","/compare/demo.js","/compare/batch.js","/api/compare/batch/info"):
                self.assertEqual(self.request(path)[0],200)
            self.assertEqual(self.request("/api/compare/batch/"+"f"*32)[0],404)
            self.assertEqual(self.request("/compare/../batch_release.py")[0],404)
            call.assert_not_called()

    def test_start_invalid_payload_and_origin_rejected(self):
        valid={"run_id":"e"*32,"rounds":3,"acknowledge_load":True}
        with patch.object(app,"start_job") as start:
            for key,value in (("run_id","http://evil/"),("rounds",True),("rounds",10),("acknowledge_load",False)):
                self.assertEqual(self.request("/api/compare/batch/start",{**valid,key:value})[0],400)
            self.assertEqual(self.request("/api/compare/batch/start",{**valid,"url":"http://evil/"})[0],400)
            self.assertEqual(self.request("/api/compare/batch/start",valid,{"Content-Type":"application/json","Origin":"http://evil"})[0],403)
            start.assert_not_called()


if __name__ == "__main__":unittest.main()