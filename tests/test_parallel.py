"""Offline real-thread tests; never send SR/LLM traffic."""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ['RACE_STAGE'])
import parallel_release as new
sys.path.insert(0, str(Path(__file__).parent.parent / 'amx-race-20261015'))
import test_race as previous

batch = new.batch


class WorkerTest(previous.WorkerTest):
    def test_all_concurrencies_counts_and_actual_cap(self):
        for c in (2, 4, 8):
            with self.subTest(c=c):
                j = previous.job(rounds=1)
                j['concurrency_per_mode'] = c
                barrier = threading.Barrier(2*c)
                lock = threading.Lock()
                active = {'on': 0, 'off': 0}
                seen = {'on': 0, 'off': 0}
                peak = {'on': 0, 'off': 0, 'total': 0}
                def fake(mode, prompt):
                    if prompt['id'].startswith('warmup-'):
                        return previous.result(mode)
                    with lock:
                        active[mode] += 1
                        seen[mode] += 1
                        first = seen[mode] <= c
                        peak[mode] = max(peak[mode], active[mode])
                        peak['total'] = max(peak['total'], sum(active.values()))
                    if first:
                        barrier.wait(5)
                    with lock:
                        active[mode] -= 1
                    return previous.result(mode)
                call = self.run_job(j, fake)
                self.assertEqual(j['state'], 'completed')
                self.assertEqual(call.call_count, 232)
                self.assertEqual(peak, {'on': c, 'off': c, 'total': 2*c})
                self.assertEqual(batch.aggregate(j['rows'], 1)['successful_pairs'], 100)
                self.assertEqual(len({(r['phase'], r['round'], r['pair_index'], r['mode']) for r in j['rows']}), 232)
                self.assertTrue(all(r['started_seconds'] <= r['completed_seconds'] for r in j['rows'] if r['phase'] == 'measured'))
                self.assertTrue(all(r['completed_seconds'] is None for r in j['rows'] if r['phase'] == 'warmup'))

    def test_pool_cancel_drains_all_inflight(self):
        j = previous.job(rounds=1)
        j['concurrency_per_mode'] = 4
        entered = threading.Event()
        drain = threading.Event()
        seen = 0
        lock = threading.Lock()
        def fake(mode, prompt):
            nonlocal seen
            if not prompt['id'].startswith('warmup-'):
                with lock:
                    seen += 1
                    if seen == 8:
                        entered.set()
                self.assertTrue(drain.wait(5))
            return previous.result(mode)
        for _ in range(4):
            batch.single.SLOTS.acquire()
        with patch.object(batch, 'evaluate', side_effect=fake):
            t = threading.Thread(target=new.concurrent_worker, args=(j, previous.DATA))
            t.start()
            try:
                self.assertTrue(entered.wait(4))
                with batch.JOB_LOCK:
                    self.assertEqual(sum(map(len, j['currents_by_mode'].values())), 8)
                    j['cancel'].set()
                self.assertFalse(batch.single.SLOTS.acquire(blocking=False))
            finally:
                drain.set()
                t.join(6)
        self.assertFalse(t.is_alive())
        self.assertEqual(j['state'], 'cancelled')
        self.assertEqual(len(j['rows']), 40)
        for _ in range(4):
            self.assertTrue(batch.single.SLOTS.acquire(blocking=False))

    def test_pool_warm_failure_and_completion_error_stop(self):
        j = previous.job(rounds=1)
        j['concurrency_per_mode'] = 8
        self.run_job(j, lambda m,p: {**previous.result(m), 'outcome': 'error', 'error': 'timeout'})
        self.assertEqual(len(j['rows']), 1)
        j = previous.job(rounds=1)
        j['concurrency_per_mode'] = 4
        self.run_job(j, lambda m,p: previous.result(m) if p['id'].startswith('warmup-') else {**previous.result(m), 'outcome': 'error', 'error': 'timeout'})
        self.assertEqual(j['state'], 'failed')
        self.assertEqual(j['reason'], 'three_consecutive_failures_per_mode_completion_order')
        self.assertLess(len(j['rows']), 232)

    def test_pool_partial_launch_failure_drains(self):
        j = previous.job(rounds=1)
        j['concurrency_per_mode'] = 4
        original = threading.Thread.start
        calls = 0
        def launch(t):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError('fixture thread launch failure')
            return original(t)
        with patch.object(threading.Thread, 'start', launch):
            self.run_job(j)
        self.assertEqual(j['state'], 'failed')
        self.assertEqual(len(j['rows']), 32)

    def test_concurrency_idempotence(self):
        with patch.object(batch, 'corpus', return_value=previous.DATA), patch.object(threading, 'Thread'):
            self.assertEqual(new.start_job('c'*32, 1, 4)[0], 202)
            self.assertEqual(new.start_job('c'*32, 1, 4)[0], 200)
            self.assertEqual(new.start_job('c'*32, 1, 8)[0], 409)
            self.assertEqual(new.start_job('c'*32, 2, 4)[0], 409)
            self.assertEqual(new.start_job('d'*32, 1, 4)[0], 409)
            self.assertEqual(batch.JOBS['c'*32]['protocol']['concurrency_global_batch'], 8)


class HTTPTest(previous.HTTPTest):
    @classmethod
    def setUpClass(cls):
        import urllib.request
        cls.server = new.portal.ThreadingHTTPServer(('127.0.0.1', 0), new.ParallelHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def test_request_contract_and_no_arbitrary_target(self):
        body = {'run_id': 'e'*32, 'rounds': 1, 'execution': 'parallel', 'acknowledge_load': True}
        with patch.object(new, 'start_job', return_value=(202, {'accepted': True})) as call:
            for c in new.CONCURRENCIES:
                self.assertEqual(self.request('/api/compare/visual/start', {**body, 'concurrency': c})[0], 202)
                call.assert_called_with('e'*32, 1, c)
            self.assertEqual(self.request('/api/compare/visual/start', body)[0], 202)
            call.assert_called_with('e'*32, 1, 1)
            call.reset_mock()
            for key, value in [('concurrency', True), ('concurrency', 3), ('concurrency', 16), ('execution', 'alternating'), ('rounds', True), ('rounds', 6), ('acknowledge_load', False)]:
                self.assertEqual(self.request('/api/compare/visual/start', {**body, key: value})[0], 400)
            self.assertEqual(self.request('/api/compare/visual/start', {**body, 'url': 'http://evil'})[0], 400)
            self.assertEqual(self.request('/api/compare/visual/start', body, {'Content-Type':'application/json', 'Origin':'http://evil'})[0], 403)
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()