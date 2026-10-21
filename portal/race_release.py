"""Additive visual comparison with truthful monotonic completion timestamps."""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import batch_release as batch

ROOT = Path(__file__).resolve().parent
portal = batch.portal
ACTIVE = {"warming", "running"}


def protocol(rounds, execution):
    p = batch.protocol(rounds)
    p.update(version="sr-visual-v2", execution=execution, requests_per_mode=100 * rounds,
             concurrency_global_batch=2 if execution == "parallel" else 1,
             measured_clock="shared Portal monotonic origin after ALL warmups; completion after eval validation",
             grid="one cell per formal request per mode; warmups excluded; success green, error red",
             launch="two gated independent C1 queues; not guaranteed simultaneous physical execution" if execution == "parallel" else "alternating paired C1 requests")
    if execution == "parallel":
        p["pair_order"] = "same deterministic question sequence in both queues; advance independently, no per-question barrier"
        p["interpretation"] = "Concurrent shared-resource comparison, not isolated causal AMX speedup; concurrency may affect timings"
    return p


def row_for(item, result, started, completed):
    phase, number, index, position, mode, prompt = item
    return {"phase": phase, "round": number, "pair_index": index, "pair_position": position,
            "mode": mode, "prompt_id": prompt["id"], "prompt_sha256": hashlib.sha256(prompt["text"].encode()).hexdigest(),
            "language": prompt.get("language"), "intended_tier": prompt.get("intended_tier"),
            "length_band": prompt.get("length_band"), "received_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "started_seconds": started, "completed_seconds": completed, **result}


def worker(job, data):
    """One batch owns all four comparison slots until ALL in-flight work is drained."""
    origin = None
    state, reason = "completed", None
    threads = []
    gate = threading.Event()

    def stopped():
        return job.get("failure_reason") or batch.stop_reason(job)

    def perform(item):
        phase, number, index, position, mode, prompt = item
        with batch.JOB_LOCK:
            if stopped():
                return False
            started = time.monotonic() - origin if origin is not None else None
            current = {"phase": phase, "round": number, "pair_index": index, "prompt_id": prompt["id"], "mode": mode}
            job["current_by_mode"][mode] = current
            job["current"] = current
        result = batch.evaluate(mode, prompt)
        completed = time.monotonic() - origin if origin is not None else None
        with batch.JOB_LOCK:
            row = row_for(item, result, started, completed)
            row["sequence"] = len(job["rows"]) + 1
            job["rows"].append(row)
            job["current_by_mode"][mode] = None
            job["current"] = next((v for v in job["current_by_mode"].values() if v), None)
            if phase == "warmup" and result["outcome"] != "ok":
                job["failure_reason"] = "warmup_failed"
            return result["outcome"] == "ok"

    def lane(items):
        streak = 0
        gate.wait()
        try:
            for item in items:
                with batch.JOB_LOCK:
                    if stopped():
                        break
                ok = perform(item)
                streak = 0 if ok else streak + 1
                if streak >= 3:
                    with batch.JOB_LOCK:
                        job["failure_reason"] = "three_consecutive_failures_per_queue"
                    break
        except Exception:
            with batch.JOB_LOCK:
                job["failure_reason"] = "internal_worker_error"

    try:
        items = list(batch.schedule(data, job["rounds"]))
        warmups = [i for i in items if i[0] == "warmup"]
        measured = [i for i in items if i[0] == "measured"]
        for item in warmups:
            with batch.JOB_LOCK:
                if stopped():
                    break
            perform(item)
        with batch.JOB_LOCK:
            proceed = not stopped()
            if proceed:
                job["state"] = "running"
        if proceed and job["execution"] == "parallel":
            # Gate both lanes until thread creation is complete; launch skew stays visible in row timestamps.
            for mode in ("off", "on"):
                thread = threading.Thread(target=lane, args=([i for i in measured if i[4] == mode],), daemon=True)
                thread.start()
                threads.append(thread)
            with batch.JOB_LOCK:
                origin = time.monotonic()
                job["measured_origin"] = origin
            gate.set()
            for thread in threads:
                thread.join()
        elif proceed:
            with batch.JOB_LOCK:
                origin = time.monotonic()
                job["measured_origin"] = origin
            gate.set()
            lane(measured)
    except Exception:
        with batch.JOB_LOCK:
            job["failure_reason"] = "internal_worker_error"
    finally:
        gate.set()
        for thread in threads:
            thread.join()
        with batch.JOB_LOCK:
            reason = stopped()
            if job.get("failure_reason"):
                state = "failed"
            elif reason:
                state = "cancelled"
            elif any(r["outcome"] != "ok" for r in job["rows"]):
                state, reason = "completed_with_errors", "failed_rows_retained"
            job.update(state=state, reason=reason, current=None, current_by_mode={"off": None, "on": None},
                       ended_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       wall_seconds=time.monotonic() - job["started_mono"],
                       measured_elapsed_seconds=time.monotonic() - origin if origin is not None else None)
            for _ in range(4):
                batch.single.SLOTS.release()


def start_job(token, rounds, execution):
    with batch.JOB_LOCK:
        if token in batch.JOBS:
            job = batch.JOBS[token]
            if job["rounds"] != rounds or job.get("execution", "alternating") != execution:
                return 409, {"error": "同一 run ID 的參數不同；未重送。"}
            job["heartbeat"] = time.monotonic()
            return 200, {"run_id": token, "state": job["state"], "reused": True}
        acquired = 0
        for _ in range(4):
            if not batch.single.SLOTS.acquire(blocking=False):
                for _ in range(acquired):
                    batch.single.SLOTS.release()
                return 409, {"error": "Portal 有其他比較進行中，未啟動新請求。"}
            acquired += 1
        try:
            data = batch.corpus()
            now = time.monotonic()
            for key in list(batch.JOBS):
                if now - batch.JOBS[key]["started_mono"] > batch.RETENTION_SECONDS:
                    del batch.JOBS[key]
            if len(batch.JOBS) >= 8:
                raise ValueError("retention limit")
            job = {"run_id": token, "rounds": rounds, "execution": execution, "state": "warming", "reason": None,
                   "rows": [], "current": None, "current_by_mode": {"on": None, "off": None},
                   "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "started_mono": now,
                   "heartbeat": now, "cancel": threading.Event(), "protocol": protocol(rounds, execution),
                   "user_load_acknowledged": True}
            batch.JOBS[token] = job
            threading.Thread(target=worker, args=(job, data), daemon=True).start()
        except Exception:
            batch.JOBS.pop(token, None)
            for _ in range(4):
                batch.single.SLOTS.release()
            return 503, {"error": "批次準備失敗，未啟動。"}
        return 202, {"run_id": token, "state": job["state"], "reused": False}


def snapshot(token):
    with batch.JOB_LOCK:
        result = batch.snapshot(token, heartbeat=True)
        if result is None:
            return None
        origin = result.pop("measured_origin", None)
        if origin is not None and result["state"] in ACTIVE:
            result["measured_elapsed_seconds"] = time.monotonic() - origin
    return result


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("visual UI anchor missing or ambiguous")
    return text.replace(old, new, 1)


def page_html():
    html = batch.comparison_html()
    html = replace_once(html, '<script src="/compare/batch.js" defer></script>',
                        '<script src="/compare/race.js" defer></script><script src="/compare/batch.js" defer></script>')
    html = replace_once(html, '<div class="batch-cards">', (ROOT / "race_fragment.html").read_text() + '<div class="batch-cards">')
    html = replace_once(html, '<label for="batch-rounds">正式輪次</label><select id="batch-rounds"><option value="1">1 輪 · 200 筆</option><option value="3" selected>3 輪 · 600 筆</option><option value="5">5 輪 · 1000 筆</option></select>',
        '<label for="batch-rounds">每側正式請求</label><select id="batch-rounds">' + ''.join(
            '<option value="%d"%s>每側 %d 筆 · %d 輪</option>' % (r, ' selected' if r == 2 else '', 100*r, r) for r in range(1, 6)) +
        '</select><label for="race-execution">執行方式</label><select id="race-execution"><option value="parallel">雙側獨立佇列 Demo · 每側 C=1</option><option value="alternating">交替配對 · 全域 C=1</option></select>')
    html = replace_once(html, '③ ON→OFF / OFF→ON 交替', '③ 選擇雙側佇列或交替配對')
    html = replace_once(html, '④ 一次一筆 · 不重試', '④ 每側一次一筆 · 不重試')
    html = replace_once(html, '以 Complexity 分類耗時為主，避免 LLM 生成時間蓋過 CPU 差異。',
                         '完成格與曲線依真實回應更新，另列 Complexity 分類耗時；不預設哪側較快。')
    html = replace_once(html, '正式連續三筆失敗即停止', '正式同一佇列連續三筆失敗即停止')
    html = replace_once(html, '同輪兩側題序相同，逐題交替先後，下一輪反轉起始側；題序 seed 與實際順序保留於 JSON。',
                         '同輪兩側題序相同。獨立佇列模式共同起跑後各自前進，不逐題等待另一側；交替模式則逐題輪替先後。模式、題序與實際完成時間皆保留於下載。')
    return html


def controller_js():
    js = (ROOT / "batch.js").read_text()
    js = replace_once(js, 'text("batch-budget", `暖機 32 筆＋正式 ${rounds * 200} 筆＝最多 ${rounds * 200 + 32} 筆 SR-only 請求；並行數 C=1。`);',
        'const execution = el("race-execution").value;\n    text("batch-budget", `每側 ${rounds * 100} 筆／格，正式合計 ${rounds * 200} 筆＋暖機 32 筆。${execution === "parallel" ? "雙側独立前進，每側 C=1，合計最多 2 筆在途。" : "交替配對，全域 C=1；不是競跑。"}`);\n    if (!latest) window.RaceVisual.reset(rounds * 100, execution);')
    js = replace_once(js, 'el("batch-rounds").disabled = busy;', 'el("race-execution").disabled = busy; el("batch-rounds").disabled = busy;')
    js = replace_once(js, 'el("batch-rounds").addEventListener("change", budget);',
        'el("batch-rounds").addEventListener("change", budget);\n  el("race-execution").addEventListener("change", budget);')
    js = replace_once(js, 'latest = data; busy = activeStates.has(data.state); runId = data.run_id;',
        'latest = data; busy = activeStates.has(data.state); runId = data.run_id;\n    el("batch-rounds").value = String(data.rounds); el("race-execution").value = data.execution || "alternating"; budget();\n    window.RaceVisual.render(data);')
    js = replace_once(js, 'body:JSON.stringify({run_id:runId,rounds:Number(el("batch-rounds").value),acknowledge_load:true})',
        'body:JSON.stringify({run_id:runId,rounds:Number(el("batch-rounds").value),execution:el("race-execution").value,acknowledge_load:true})')
    js = replace_once(js, '"/api/compare/batch/start"', '"/api/compare/visual/start"')
    js = replace_once(js, '"/api/compare/batch/info"', '"/api/compare/visual/info"')
    js = replace_once(js, 'setTimeout(poll, 1000)', 'setTimeout(poll, 250)')
    js = replace_once(js, '"complexity","received_utc"]', '"complexity","received_utc","started_seconds","completed_seconds"]')
    js = replace_once(js, 'const fields = ["sequence"', 'const fields = ["execution","sequence"')
    js = replace_once(js, 'fields.map(f=>csvCell(r[f]))', 'fields.map(f=>csvCell(f === "execution" ? (latest.execution || "alternating") : r[f]))')
    return js


class VisualHandler(batch.BatchHandler):
    def do_GET(self):
        if self.requestline.split()[1] != self.path:
            return super().do_GET()
        if self.path == "/api/compare/visual/info":
            try:
                data = batch.corpus()
                return self._send_amx_json(200, {"available": True, "count": len(data["prompts"]), "warmups": len(data["warmups"]),
                    "corpus_sha256": batch.CORPUS_SHA, "round_options": list(range(1, 6)), "default_rounds": 2,
                    "execution_options": ["parallel", "alternating"], "default_execution": "parallel", "protocol": protocol(2, "parallel")})
            except Exception:
                return self._send_amx_json(503, {"available": False, "error": "題庫驗證失敗，未送出請求。"})
        bodies = {"/compare/": (page_html, "text/html"), "/compare/batch.js": (controller_js, "text/javascript"),
                  "/compare/race.js": (lambda: (ROOT / "race.js").read_text(), "text/javascript")}
        if self.path in bodies:
            fn, mime = bodies[self.path]
            raw = fn().encode()
            self.send_response(200)
            for key, val in {"Content-Type": mime + "; charset=utf-8", "Content-Length": str(len(raw)), "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(raw)
            return
        match = re.fullmatch(r"/api/compare/batch/([0-9a-f]{32})", self.path)
        if match:
            result = snapshot(match[1])
            return self._send_amx_json(200 if result else 404, result or {"error": "run 不存在或已過期，不會自動重跑。"})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/compare/visual/start":
            return super().do_POST()
        self.close_connection = True
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")):
            return self._send_amx_json(403, {"error": "same-origin only"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self._send_amx_json(415, {"error": "JSON required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 1024:
                raise ValueError()
            self.connection.settimeout(10)
            b = json.loads(self.rfile.read(length))
            if (not isinstance(b, dict) or set(b) != {"run_id", "rounds", "execution", "acknowledge_load"}
                    or not isinstance(b["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", b["run_id"])
                    or type(b["rounds"]) is not int or b["rounds"] not in range(1, 6)
                    or b["execution"] not in ("parallel", "alternating") or b["acknowledge_load"] is not True):
                raise ValueError()
        except Exception:
            return self._send_amx_json(400, {"error": "需有效 run ID、1–5 輪、parallel/alternating 模式及負載確認。"})
        code, result = start_job(b["run_id"], b["rounds"], b["execution"])
        self._send_amx_json(code, result)


portal.Handler = VisualHandler

if __name__ == "__main__":
    portal.main()