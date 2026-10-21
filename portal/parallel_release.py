"""Parallel-only UI, 60s initial axis, and bounded SR-only concurrency trials."""
import json
import re
import threading
import time
from collections import deque

import chart_release as chart

race = chart.race
batch = race.batch
portal = chart.portal
previous_page = race.page_html
previous_worker = race.worker
previous_controller = race.controller_js
CONCURRENCIES = (1, 2, 4, 8)


def page_html():
    html = previous_page()
    html = race.replace_once(html,
        '<label for="race-execution">執行方式</label><select id="race-execution"><option value="parallel">雙側獨立佇列 Demo · 每側 C=1</option><option value="alternating">交替配對 · 全域 C=1</option></select>',
        '<input type="hidden" id="race-execution" value="parallel"><span>雙側同時起跑 · 每側 C=1</span>')
    html = race.replace_once(html, '③ 選擇雙側佇列或交替配對', '③ 雙側同時起跑，各自前進')
    html = race.replace_once(html,
        '同輪兩側題序相同。獨立佇列模式共同起跑後各自前進，不逐題等待另一側；交替模式則逐題輪替先後。模式、題序與實際完成時間皆保留於下載。',
        '同輪兩側題序相同，共同起跑後各自前進，不逐題等待另一側。題序、並行數與實際完成時間皆保留於下載；這是共享資源下的速度展示。')
    return html


def controller_js():
    js = previous_controller()
    # New starts are always parallel, even after reconnecting to an old alternating result.
    js = race.replace_once(js, 'execution:el("race-execution").value,acknowledge_load:true',
                          'execution:"parallel",acknowledge_load:true')
    js = race.replace_once(js, 'const fields = ["execution",', 'const fields = ["concurrency_per_mode","execution",')
    js = race.replace_once(js, 'f === "execution" ? (latest.execution || "alternating") : r[f]',
                          'f === "concurrency_per_mode" ? (latest.concurrency_per_mode || 1) : f === "execution" ? (latest.execution || "alternating") : r[f]')
    js = race.replace_once(js, '等待目前一筆結束', '等待所有在途請求結束')
    return js


def chart_js():
    js = chart.chart_js()
    assert js.count('axisEnd=30;') == 2
    js = js.replace('axisEnd=30;', 'axisEnd=60;')
    js = race.replace_once(js, 'const current=data.current_by_mode?.[mode] || (data.current?.mode===mode?data.current:null);',
        'const current=data.current_by_mode?.[mode] || (data.current?.mode===mode?data.current:null);\n      const currents=data.currents_by_mode?.[mode] || (current?[current]:[]);')
    js = race.replace_once(js, 'active&&current?.phase==="measured"&&(current.round-1)*100+current.pair_index===i?',
        'active&&currents.some(c=>c.phase==="measured"&&(c.round-1)*100+c.pair_index===i)?')
    js = race.replace_once(js, 'const inFlight=active&&current?.phase==="measured"?1:0;',
        'const inFlight=active?currents.filter(c=>c.phase==="measured").length:0;')
    js = race.replace_once(js, 'lastReceived=performance.now();lastState=data.state;',
        'lastReceived=performance.now();lastState=data.state;\n    if(selected==="parallel")set("race-mode",`雙側獨立佇列 · 每側 C=${data.concurrency_per_mode||1} · 合計 C≤${2*(data.concurrency_per_mode||1)}`);')
    return js


def concurrent_worker(job, data):
    # start_job installs the protocol under this lock before a new worker proceeds.
    with batch.JOB_LOCK:
        concurrency = job.get('concurrency_per_mode', 1)
    if concurrency == 1:
        return previous_worker(job, data)
    origin = None
    threads = []
    gate = threading.Event()
    active = {'on': {}, 'off': {}}
    streak = {'on': 0, 'off': 0}

    def stopped():
        return job.get('failure_reason') or batch.stop_reason(job)

    def set_current():
        job['currents_by_mode'] = {m: list(items.values()) for m, items in active.items()}
        job['current_by_mode'] = {m: next(iter(items.values()), None) for m, items in active.items()}
        job['current'] = next((c for c in job['current_by_mode'].values() if c), None)

    def perform(item):
        phase, number, index, position, mode, prompt = item
        key = (phase, number, index)
        with batch.JOB_LOCK:
            if stopped():
                return
            started = time.monotonic() - origin if origin is not None else None
            active[mode][key] = {'phase': phase, 'round': number, 'pair_index': index, 'mode': mode, 'prompt_id': prompt['id']}
            set_current()
        try:
            result = batch.evaluate(mode, prompt)
            completed = time.monotonic() - origin if origin is not None else None
            with batch.JOB_LOCK:
                row = race.row_for(item, result, started, completed)
                row['sequence'] = len(job['rows']) + 1
                job['rows'].append(row)
                streak[mode] = 0 if result['outcome'] == 'ok' else streak[mode] + 1
                if phase == 'warmup' and result['outcome'] != 'ok':
                    job['failure_reason'] = 'warmup_failed'
                elif streak[mode] >= 3:
                    job['failure_reason'] = 'three_consecutive_failures_per_mode_completion_order'
        finally:
            with batch.JOB_LOCK:
                active[mode].pop(key, None)
                set_current()

    def lane(queue):
        gate.wait()
        try:
            while True:
                with batch.JOB_LOCK:
                    if stopped() or not queue:
                        return
                    item = queue.popleft()
                perform(item)
        except Exception:
            with batch.JOB_LOCK:
                job['failure_reason'] = 'internal_worker_error'

    try:
        items = list(batch.schedule(data, job['rounds']))
        for item in items:
            if item[0] != 'warmup':
                continue
            with batch.JOB_LOCK:
                if stopped():
                    break
            perform(item)
        with batch.JOB_LOCK:
            proceed = not stopped()
        if proceed:
            for mode in ('off', 'on'):
                queue = deque(i for i in items if i[0] == 'measured' and i[4] == mode)
                for _ in range(concurrency):
                    thread = threading.Thread(target=lane, args=(queue,), daemon=True)
                    thread.start()
                    threads.append(thread)
            with batch.JOB_LOCK:
                origin = time.monotonic()
                job.update(state='running', measured_origin=origin)
            gate.set()
    except Exception:
        with batch.JOB_LOCK:
            job['failure_reason'] = 'internal_worker_error'
    finally:
        gate.set()
        for thread in threads:
            thread.join()
        with batch.JOB_LOCK:
            reason = stopped()
            state = 'failed' if job.get('failure_reason') else 'cancelled' if reason else 'completed_with_errors' if any(r['outcome'] != 'ok' for r in job['rows']) else 'completed'
            job.update(state=state, reason=reason, current=None, current_by_mode={'on': None, 'off': None},
                       currents_by_mode={'on': [], 'off': []}, ended_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       wall_seconds=time.monotonic()-job['started_mono'], measured_elapsed_seconds=time.monotonic()-origin if origin is not None else None)
            for _ in range(4):
                batch.single.SLOTS.release()


def start_job(token, rounds, concurrency):
    with batch.JOB_LOCK:
        existing = batch.JOBS.get(token)
        if existing and (existing.get('concurrency_per_mode', 1) != concurrency or existing.get('execution', 'alternating') != 'parallel'):
            return 409, {'error': '同一 run ID 的模式或 concurrency 不同；未重送。'}
        code, result = race.start_job(token, rounds, 'parallel')
        if code == 202:
            job = batch.JOBS[token]
            job['concurrency_per_mode'] = concurrency
            job['protocol'].update(concurrency_per_mode=concurrency, concurrency_global_batch=2*concurrency,
                version='sr-parallel-v3', launch='shared gated start; bounded independent per-mode worker pools',
                error_stop='warmup failure or three consecutive formal errors per mode in completion order; drain inflight')
        return code, result


class ParallelHandler(chart.ChartHandler):
    def do_GET(self):
        if self.path == '/compare/race.js' and self.requestline.split()[1] == self.path:
            raw = chart_js().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == '/api/compare/parallel/status':
            with batch.JOB_LOCK:
                busy = any(j['state'] in race.ACTIVE for j in batch.JOBS.values())
            return self._send_amx_json(200, {'active_batch': busy, 'concurrency_options': list(CONCURRENCIES)})
        if self.path == '/api/compare/visual/info':
            try:
                data = batch.corpus()
                return self._send_amx_json(200, {'available': True, 'count': len(data['prompts']), 'warmups': len(data['warmups']),
                    'corpus_sha256': batch.CORPUS_SHA, 'execution_options': ['parallel'], 'default_execution': 'parallel',
                    'round_options': list(range(1, 6)), 'default_rounds': 2, 'default_concurrency_per_mode': 1})
            except Exception:
                return self._send_amx_json(503, {'available': False, 'error': '題庫驗證失敗，未送出請求。'})
        return super().do_GET()

    def do_POST(self):
        if self.path != '/api/compare/visual/start':
            return super().do_POST()
        self.close_connection = True
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            return self._send_amx_json(403, {'error': 'same-origin only'})
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self._send_amx_json(415, {'error': 'JSON required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 1024:
                raise ValueError()
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(length))
            required = {'run_id', 'rounds', 'execution', 'acknowledge_load'}
            if not isinstance(data, dict) or set(data) not in (required, required | {'concurrency'}):
                raise ValueError()
            c = data.get('concurrency', 1)
            if (not isinstance(data['run_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', data['run_id'])
                    or type(data['rounds']) is not int or data['rounds'] not in range(1, 6)
                    or data['execution'] != 'parallel' or data['acknowledge_load'] is not True
                    or type(c) is not int or c not in CONCURRENCIES):
                raise ValueError()
        except Exception:
            return self._send_amx_json(400, {'error': '僅支援 parallel、1–5 輪及每側 C=1/2/4/8；需負載確認。'})
        code, result = start_job(data['run_id'], data['rounds'], c)
        return self._send_amx_json(code, result)


race.page_html = page_html
race.controller_js = controller_js
race.worker = concurrent_worker
portal.Handler = ParallelHandler

if __name__ == '__main__':
    portal.main()