"""Offline C15 contract and true worker-concurrency tests, no inference."""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,os.environ['RACE_STAGE'])
import c15_release as new
sys.path.insert(0,str(Path(__file__).parent.parent/'amx-parallel-20261015'))
import test_parallel as previous


class HTTPTest(previous.HTTPTest):
    @classmethod
    def setUpClass(cls):
        import urllib.request
        cls.server=new.portal.ThreadingHTTPServer(('127.0.0.1',0),new.C15Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        cls.client=urllib.request.build_opener(urllib.request.ProxyHandler({}))


class C15Test(unittest.TestCase):
    def test_15_workers_per_side_and_exact_counts(self):
        b=new.parallel.batch
        b.JOBS.clear()
        b.single.SLOTS=threading.BoundedSemaphore(4)
        j=previous.previous.job(rounds=1)
        j['concurrency_per_mode']=15
        barrier=threading.Barrier(30)
        lock=threading.Lock()
        seen={'on':0,'off':0}
        active={'on':0,'off':0}
        peak={'on':0,'off':0}
        def fake(mode,prompt):
            if prompt['id'].startswith('warmup-'):return previous.previous.result(mode)
            with lock:
                seen[mode]+=1
                first=seen[mode]<=15
                active[mode]+=1
                peak[mode]=max(peak[mode],active[mode])
            if first:barrier.wait(5)
            with lock:active[mode]-=1
            return previous.previous.result(mode)
        for _ in range(4):b.single.SLOTS.acquire()
        with patch.object(b,'evaluate',new=fake):new.parallel.concurrent_worker(j,previous.previous.DATA)
        self.assertEqual(j['state'],'completed')
        self.assertEqual(seen,{'on':100,'off':100})
        self.assertEqual(peak,{'on':15,'off':15})
        self.assertEqual(len(j['rows']),232)
        self.assertEqual(b.aggregate(j['rows'],1)['successful_pairs'],100)
        for _ in range(4):self.assertTrue(b.single.SLOTS.acquire(blocking=False))
        for _ in range(4):b.single.SLOTS.release()

    def test_ui_request_and_english_preserved(self):
        p=new.pages()
        self.assertIn('<option value="15" selected>',p['/compare/'][0])
        self.assertIn('concurrency:Number(el("race-concurrency").value)',p['/compare/batch.js'][0])
        self.assertIn('String(data.concurrency_per_mode || 1)',p['/compare/batch.js'][0])
        self.assertIn('lang="en"',p['/compare/'][0])
        self.assertEqual(p['/compare/demo.js'],new.original_pages()['/compare/demo.js'])


if __name__=='__main__':unittest.main()