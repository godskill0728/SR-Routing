"""Offline tests, actual threads but fake eval; no cluster/LLM traffic."""
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

sys.path.insert(0, os.environ["RACE_STAGE"])
import race_release as race
batch = race.batch
DATA = json.loads((Path(__file__).resolve().parent.parent / "reports-public" / "corpus.json").read_text())


def result(mode):
    return {"outcome": "ok", "error": None, "http_status": 200, "http_seconds": .02,
            "complexity_seconds": .01, "decision": "route-medium", "models": ["gemma"], "complexity": ["medium"]}


def job(execution="parallel", rounds=2):
    now = time.monotonic()
    return {"run_id": "a" * 32, "rounds": rounds, "execution": execution, "state": "warming", "reason": None,
            "rows": [], "current": None, "current_by_mode": {"on": None, "off": None},
            "created_utc": "2026-10-15T00:00:00Z", "started_mono": now, "heartbeat": now,
            "cancel": threading.Event(), "protocol": race.protocol(rounds, execution)}


class WorkerTest(unittest.TestCase):
    def setUp(self):
        batch.JOBS.clear()
        batch.single.SLOTS = threading.BoundedSemaphore(4)

    def run_job(self, j, evaluate=None):
        for _ in range(4): batch.single.SLOTS.acquire()
        with patch.object(batch, "evaluate", side_effect=evaluate or (lambda m,p: result(m))) as call:
            race.worker(j, DATA)
        for _ in range(4): self.assertTrue(batch.single.SLOTS.acquire(blocking=False))
        self.assertFalse(batch.single.SLOTS.acquire(blocking=False))
        for _ in range(4): batch.single.SLOTS.release()
        return call

    def test_parallel_count_timestamps_and_pairing(self):
        j=job(rounds=4);call=self.run_job(j)
        self.assertEqual(call.call_count,832)
        self.assertEqual(j["state"],"completed")
        measured=[r for r in j["rows"] if r["phase"]=="measured"]
        for m in ("on","off"):
            rows=[r for r in measured if r["mode"]==m]
            self.assertEqual(len(rows),400)
            self.assertEqual(len({(r["round"],r["pair_index"]) for r in rows}),400)
            self.assertTrue(all(0 <= r["started_seconds"] <= r["completed_seconds"] for r in rows))
            self.assertEqual([r["completed_seconds"] for r in rows],sorted(r["completed_seconds"] for r in rows))
        self.assertTrue(all(r["completed_seconds"] is None for r in j["rows"] if r["phase"]=="warmup"))
        self.assertEqual(sorted(r["sequence"] for r in j["rows"]),list(range(1,833)))
        self.assertEqual(batch.aggregate(j["rows"],4)["successful_pairs"],400)

    def test_independent_lanes_no_per_pair_barrier_max_two_inflight(self):
        j=job();on_ahead=threading.Event();off_entered=threading.Event();lock=threading.Lock()
        active={"on":0,"off":0};seen={"on":0,"off":0};max_active=0
        def fake(mode,prompt):
            nonlocal max_active
            if prompt["id"].startswith("warmup-"):return result(mode)
            with lock:
                active[mode]+=1;seen[mode]+=1
                self.assertEqual(active[mode],1)
                max_active=max(max_active,sum(active.values()))
                nth=seen[mode]
            if mode=="off" and nth==1:
                off_entered.set();self.assertTrue(on_ahead.wait(3))
            if mode=="on" and nth==1:self.assertTrue(off_entered.wait(3))
            if mode=="on" and nth==2:on_ahead.set()
            with lock:active[mode]-=1
            return result(mode)
        self.run_job(j,fake)
        self.assertEqual(j["state"],"completed")
        self.assertEqual(max_active,2)
        self.assertTrue(on_ahead.is_set())

    def test_alternating_has_one_inflight_order_unchanged(self):
        j=job("alternating",1);call=self.run_job(j)
        self.assertEqual(call.call_count,232)
        self.assertEqual([r["mode"] for r in j["rows"]],[i[4] for i in batch.schedule(DATA,1)])
        measured=[r for r in j["rows"] if r["phase"]=="measured"]
        self.assertTrue(all(a["completed_seconds"]<=b["started_seconds"] for a,b in zip(measured,measured[1:])))
        self.assertEqual(j["protocol"]["concurrency_global_batch"],1)

    def test_cancel_waits_for_inflight_before_release(self):
        j=job();entered=threading.Event();drain=threading.Event()
        def fake(mode,prompt):
            if not prompt["id"].startswith("warmup-"):
                entered.set();drain.wait(4)
            return result(mode)
        for _ in range(4):batch.single.SLOTS.acquire()
        with patch.object(batch,"evaluate",side_effect=fake):
            t=threading.Thread(target=race.worker,args=(j,DATA));t.start()
            try:
                self.assertTrue(entered.wait(3));j["cancel"].set()
                self.assertFalse(batch.single.SLOTS.acquire(blocking=False))
            finally:drain.set();t.join(5)
        self.assertFalse(t.is_alive());self.assertEqual(j["state"],"cancelled")
        self.assertLessEqual(len(j["rows"]),34)
        for _ in range(4):self.assertTrue(batch.single.SLOTS.acquire(blocking=False))

    def test_warmup_fail_and_time_limits_no_formal(self):
        j=job();self.run_job(j,lambda m,p:{**result(m),"outcome":"error","error":"timeout"})
        self.assertEqual(len(j["rows"]),1);self.assertEqual(j["reason"],"warmup_failed")
        for field,seconds,reason in (("heartbeat",46,"browser_lease_expired"),("started_mono",1201,"wall_time_limit")):
            j=job();j[field]-=seconds;call=self.run_job(j)
            call.assert_not_called();self.assertEqual(j["reason"],reason)

    def test_three_errors_and_other_lane_exception_drain(self):
        j=job()
        def fake(mode,prompt):
            return result(mode) if prompt["id"].startswith("warmup-") or mode=="off" else {**result(mode),"outcome":"error","error":"timeout","complexity_seconds":None}
        self.run_job(j,fake)
        self.assertEqual(j["state"],"failed")
        self.assertEqual(sum(r["outcome"]!="ok" for r in j["rows"]),3)
        self.assertTrue(all(v is None for v in j["current_by_mode"].values()))

    def test_start_idempotence_includes_execution_and_rounds(self):
        with patch.object(batch,"corpus",return_value=DATA),patch.object(race.threading,"Thread") as thread:
            self.assertEqual(race.start_job("a"*32,2,"parallel")[0],202)
            self.assertEqual(race.start_job("a"*32,2,"parallel")[0],200)
            self.assertEqual(race.start_job("a"*32,2,"alternating")[0],409)
            self.assertEqual(race.start_job("a"*32,4,"parallel")[0],409)
            self.assertEqual(race.start_job("b"*32,2,"parallel")[0],409)
            self.assertEqual(thread.call_count,1)

    def test_launch_failure_releases_all_slots(self):
        with patch.object(batch,"corpus",return_value=DATA),patch.object(race.threading,"Thread") as thread:
            thread.return_value.start.side_effect=RuntimeError("cannot launch")
            self.assertEqual(race.start_job("a"*32,2,"parallel")[0],503)
        self.assertEqual(batch.JOBS,{})
        for _ in range(4):self.assertTrue(batch.single.SLOTS.acquire(blocking=False))

    def test_snapshot_relative_times_only(self):
        j=job();batch.JOBS[j["run_id"]]=j;self.run_job(j)
        s=race.snapshot(j["run_id"])
        self.assertNotIn("measured_origin",s)
        self.assertGreaterEqual(s["measured_elapsed_seconds"],max(r["completed_seconds"] or 0 for r in s["rows"]))
        self.assertEqual(s["summary"]["successful_pairs"],200)
        json.dumps(s,allow_nan=False)


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=portal_server=race.portal.ThreadingHTTPServer(("127.0.0.1",0),race.VisualHandler)
        cls.thread=threading.Thread(target=portal_server.serve_forever,daemon=True);cls.thread.start()
        cls.base="http://127.0.0.1:"+str(cls.server.server_port)
        cls.client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=headers or {"Content-Type":"application/json"})
        try:r=self.client.open(req,timeout=5)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,r.read()
    def test_no_inference_on_view_info(self):
        with patch.object(batch,"corpus",return_value=DATA),patch.object(batch,"evaluate") as eval:
            for p in ("/compare/","/compare/race.js","/compare/batch.js","/api/compare/visual/info"):
                self.assertEqual(self.request(p)[0],200)
            eval.assert_not_called()
    def test_request_contract_and_no_arbitrary_target(self):
        b={"run_id":"c"*32,"rounds":2,"execution":"parallel","acknowledge_load":True}
        with patch.object(race,"start_job",return_value=(202,{"accepted":True})) as call:
            self.assertEqual(self.request("/api/compare/visual/start",b)[0],202)
            call.assert_called_once_with("c"*32,2,"parallel");call.reset_mock()
            for key,value in (("rounds",True),("rounds",6),("execution","http://evil/"),("acknowledge_load",False)):
                self.assertEqual(self.request("/api/compare/visual/start",{**b,key:value})[0],400)
            self.assertEqual(self.request("/api/compare/visual/start",{**b,"url":"http://evil"})[0],400)
            self.assertEqual(self.request("/api/compare/visual/start",b,{"Content-Type":"application/json","Origin":"http://evil"})[0],403)
            call.assert_not_called()


if __name__ == "__main__":unittest.main()