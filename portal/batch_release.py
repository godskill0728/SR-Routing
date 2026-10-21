"""Additive, bounded SR-only corpus benchmark. Never reconfigure routers or retry evals."""
import copy
import hashlib
import json
import math
import os
import random
import re
import socket
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import compare_release as single

portal = single.portal
ROOT = Path(__file__).resolve().parent
CORPUS_SHA = os.environ.get("CORPUS_SHA256") or (ROOT.parent / "reports-public" / "corpus.sha256").read_text().strip()
EVAL_URLS = {
    "on": os.environ.get("EVAL_URL_ON", "http://127.0.0.1:9/api/v1/eval"),
    "off": os.environ.get("EVAL_URL_OFF", "http://127.0.0.1:9/api/v1/eval"),
}
JOB_LOCK = threading.RLock()
JOBS = {}
LEASE_SECONDS = 45
MAX_SECONDS = 1200
RETENTION_SECONDS = 3600


def corpus():
    raw = (portal.REPORTS_ROOT / "corpus.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA:
        raise ValueError("Corpus changed; review required")
    data = json.loads(raw)
    prompts, warmups = data["prompts"], data["warmups"]
    if len(prompts) != 100 or len({p["id"] for p in prompts}) != 100 or len(warmups) != 16:
        raise ValueError("Invalid corpus size")
    for text in [p["text"] for p in prompts] + warmups:
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ValueError("Invalid corpus text")
    return data


def protocol(rounds):
    return {"version": "sr-only-paired-v1", "endpoint": "/api/v1/eval", "gpu_generation": False,
            "rounds": rounds, "questions_per_round": 100, "concurrency_global_batch": 1,
            "warmups_per_mode": 16, "warmup_schedule": "once before measured rounds, excluded from statistics",
            "formal_requests": rounds * 200, "warmup_requests": 32,
            "pair_order": "per shuffled question, ON/OFF then OFF/ON; inverted on alternate rounds",
            "shuffle": "Python random.Random(20260907 + round_index).shuffle; actual order retained in rows",
            "eval_body": {"text": "<exact corpus text>"}, "retries": 0,
            "complexity_scope": "metrics.complexity.execution_time_ms: complexity classifier wall time, not pure embedding kernel",
            "http_scope": "Portal monotonic before HTTP open through full body read, JSON parsing excluded; not browser or LLM time",
            "percentiles": "linear interpolation at (n-1)*q", "ratio_scope": "OFF/ON on complete successful pairs only",
            "configuration_equivalence": "not verified", "amx_execution": "not verified",
            "node_exclusivity": "not reserved; other Portal/chat/cluster workloads may overlap",
            "lease_seconds": LEASE_SECONDS, "max_wall_seconds": MAX_SECONDS,
            "socket_timeout_seconds": 10, "corpus_sha256": CORPUS_SHA,
            "interpretation": "Descriptive paired comparison, not independently certified causal AMX speedup"}


def schedule(data, rounds):
    for index, text in enumerate(data["warmups"]):
        prompt = {"id": "warmup-%02d" % (index + 1), "text": text}
        for position, mode in enumerate(("on", "off") if index % 2 == 0 else ("off", "on")):
            yield "warmup", 0, index, position, mode, prompt
    for round_index in range(rounds):
        prompts = list(data["prompts"])
        random.Random(20260907 + round_index).shuffle(prompts)
        for index, prompt in enumerate(prompts):
            order = ("on", "off") if (index + round_index) % 2 == 0 else ("off", "on")
            for position, mode in enumerate(order):
                yield "measured", round_index + 1, index, position, mode, prompt


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None}
    def percentile(q):
        n = (len(values) - 1) * q
        low, high = math.floor(n), math.ceil(n)
        return values[low] + (values[high] - values[low]) * (n - low)
    return {"n": len(values), "mean": statistics.mean(values), "p50": percentile(.5),
            "p95": percentile(.95), "min": values[0], "max": values[-1]}


def aggregate(rows, rounds):
    measured = [r for r in rows if r["phase"] == "measured"]
    warmups = [r for r in rows if r["phase"] == "warmup"]
    modes = {}
    for mode in ("on", "off"):
        selected = [r for r in measured if r["mode"] == mode]
        good = [r for r in selected if r["outcome"] == "ok"]
        modes[mode] = {"planned": rounds * 100, "attempted": len(selected), "success": len(good),
                       "failed": len(selected) - len(good), "unattempted": rounds * 100 - len(selected),
                       "complexity_seconds": stats([r["complexity_seconds"] for r in good]),
                       "http_seconds": stats([r["http_seconds"] for r in good])}
    grouped = {}
    for row in measured:
        grouped.setdefault((row["round"], row["prompt_id"]), {})[row["mode"]] = row
    good_pairs = [p for p in grouped.values() if set(p) == {"on", "off"} and all(r["outcome"] == "ok" for r in p.values())]
    ratios = {}
    for metric in ("complexity_seconds", "http_seconds"):
        on, off = [p["on"][metric] for p in good_pairs], [p["off"][metric] for p in good_pairs]
        ratios[metric] = {"ratio_of_means_off_on": sum(off) / sum(on) if on and sum(on) > 0 else None,
                          "paired_off_on": stats([b / a for a, b in zip(on, off) if a > 0])}
    agreement = {key: sum(p["on"][key] == p["off"][key] for p in good_pairs)
                 for key in ("decision", "models", "complexity")}
    by_round = []
    for number in range(1, rounds + 1):
        paired = [p for p in good_pairs if p["on"]["round"] == number]
        on_sum = sum(p["on"]["complexity_seconds"] for p in paired)
        by_round.append({"round": number, "successful_pairs": len(paired),
                         "complexity_ratio_off_on": sum(p["off"]["complexity_seconds"] for p in paired) / on_sum if on_sum else None})
    return {"modes": modes, "measured_attempts": len(measured), "warmup_attempts": len(warmups),
            "warmup_failures": sum(r["outcome"] != "ok" for r in warmups),
            "planned_pairs": rounds * 100, "successful_pairs": len(good_pairs),
            "incomplete_or_failed_pairs": len(grouped) - len(good_pairs),
            "unattempted_pairs": rounds * 100 - len(grouped), "ratios": ratios,
            "agreement_denominator": len(good_pairs), "agreement": agreement, "by_round": by_round}


def evaluate(mode, prompt):
    """Exactly one API call; never echo raw errors or backend response text."""
    result = {"outcome": "error", "error": None, "http_status": None,
              "http_seconds": None, "complexity_seconds": None, "decision": None,
              "models": [], "complexity": []}
    req = urllib.request.Request(EVAL_URLS[mode], data=json.dumps({"text": prompt["text"]}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    start = time.monotonic()
    try:
        with portal.INTERNAL_HTTP.open(req, timeout=10) as resp:
            result["http_status"] = resp.status
            raw = resp.read(524289)
        result["http_seconds"] = time.monotonic() - start
        if len(raw) > 524288:
            raise ValueError("oversized")
        data = json.loads(raw)
        ms = data.get("metrics", {}).get("complexity", {}).get("execution_time_ms")
        decision = data.get("routing_decision")
        models = data.get("recommended_models")
        complexity = data.get("decision_result", {}).get("matched_signals", {}).get("complexity")
        valid_list = lambda v: isinstance(v, list) and 1 <= len(v) <= 100 and all(isinstance(x, str) and 0 < len(x) <= 256 for x in v)
        if (type(ms) not in (int, float) or not math.isfinite(ms) or not 0 < ms <= 1_200_000
                or not isinstance(decision, str) or not 0 < len(decision) <= 256
                or not valid_list(models) or not valid_list(complexity)
                or data.get("original_text") != prompt["text"] or result["http_status"] != 200):
            raise ValueError("invalid eval response")
        result.update(outcome="ok", complexity_seconds=ms / 1000, decision=decision,
                      models=sorted(models), complexity=sorted(complexity))
    except urllib.error.HTTPError as exc:
        result.update(http_status=exc.code, error="http_error")
        exc.close()
    except (TimeoutError, socket.timeout):
        result["error"] = "timeout"
    except urllib.error.URLError as exc:
        result["error"] = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "transport_error"
    except (ValueError, TypeError, AttributeError):
        result["error"] = "invalid_eval_response"
    except Exception:
        result["error"] = "request_error"
    if result["http_seconds"] is None:
        result["http_seconds"] = time.monotonic() - start
    return result


def stop_reason(job):
    if job["cancel"].is_set():
        return "user_cancelled"
    if time.monotonic() - job["heartbeat"] > LEASE_SECONDS:
        return "browser_lease_expired"
    if time.monotonic() - job["started_mono"] > MAX_SECONDS:
        return "wall_time_limit"
    return None


def worker(job, data):
    state, reason, streak = "completed", None, 0
    try:
        for phase, number, index, position, mode, prompt in schedule(data, job["rounds"]):
            with JOB_LOCK:
                reason = stop_reason(job)
                if reason:
                    state = "cancelled"
                    break
                job.update(state="warming" if phase == "warmup" else "running",
                           current={"phase": phase, "round": number, "prompt_id": prompt["id"], "mode": mode})
            result = evaluate(mode, prompt)
            row = {"sequence": len(job["rows"]) + 1, "phase": phase, "round": number,
                   "pair_index": index, "pair_position": position, "mode": mode, "prompt_id": prompt["id"],
                   "prompt_sha256": hashlib.sha256(prompt["text"].encode()).hexdigest(),
                   "language": prompt.get("language"), "intended_tier": prompt.get("intended_tier"),
                   "length_band": prompt.get("length_band"), "received_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **result}
            with JOB_LOCK:
                job["rows"].append(row)
            streak = streak + 1 if result["outcome"] != "ok" else 0
            if (phase == "warmup" and streak) or streak >= 3:
                state, reason = "failed", "warmup_failed" if phase == "warmup" else "three_consecutive_failures"
                break
        if state == "completed" and any(r["outcome"] != "ok" for r in job["rows"]):
            state, reason = "completed_with_errors", "failed_rows_retained"
    except Exception:
        state, reason = "failed", "internal_worker_error"
    finally:
        with JOB_LOCK:
            job.update(state=state, reason=reason, current=None, ended_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       wall_seconds=time.monotonic() - job["started_mono"])
            for _ in range(4):
                single.SLOTS.release()


def start_job(token, rounds):
    with JOB_LOCK:
        if token in JOBS:
            job = JOBS[token]
            if job["rounds"] != rounds:
                return 409, {"error": "同一 run ID 的參數不同；不會重送。"}
            job["heartbeat"] = time.monotonic()
            return 200, {"run_id": token, "state": job["state"], "reused": True}
        # Taking all single-demo slots prevents a new single demo overlapping this batch.
        acquired = 0
        for _ in range(4):
            if not single.SLOTS.acquire(blocking=False):
                for _ in range(acquired):
                    single.SLOTS.release()
                return 409, {"error": "此 Portal 已有單題或批次請求，請等待完成；未送出新請求。"}
            acquired += 1
        try:
            data = corpus()
            now = time.monotonic()
            for key in list(JOBS):
                if now - JOBS[key]["started_mono"] > RETENTION_SECONDS:
                    del JOBS[key]
            if len(JOBS) >= 8:
                raise ValueError("Too many retained runs")
            job = {"run_id": token, "rounds": rounds, "state": "warming", "reason": None, "rows": [],
                   "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "started_mono": now,
                   "heartbeat": now, "cancel": threading.Event(), "current": None,
                   "protocol": protocol(rounds), "user_load_acknowledged": True}
            JOBS[token] = job
            threading.Thread(target=worker, args=(job, data), daemon=True).start()
        except Exception:
            JOBS.pop(token, None)
            for _ in range(4):
                single.SLOTS.release()
            return 503, {"error": "題庫驗證或執行準備失敗，未啟動新批次。"}
        return 202, {"run_id": token, "state": job["state"], "reused": False}


def snapshot(token, heartbeat=False):
    with JOB_LOCK:
        job = JOBS.get(token)
        if job is None or time.monotonic() - job["started_mono"] > RETENTION_SECONDS:
            return None
        if heartbeat:
            job["heartbeat"] = time.monotonic()
        result = copy.deepcopy({key: value for key, value in job.items() if key not in ("cancel", "heartbeat", "started_mono")})
        result["wall_seconds"] = job.get("wall_seconds", time.monotonic() - job["started_mono"])
    result["summary"] = aggregate(result["rows"], result["rounds"])
    return result


def comparison_html():
    original = (ROOT / "compare.html").read_text()
    if original.count('<form id="compare-form"') != 1 or original.count('</main>') != 1:
        raise RuntimeError("Compare HTML anchor drift")
    original = original.replace("輸入一次，並行送到兩組 Semantic Router。左右看分類、路由階段秒數與串流回答。",
                                "單題看完整回答，100 題看 SR-only 配對分布。將 CPU 分類耗時與 GPU 生成時間分開比較。", 1)
    original = original.replace("ONE PROMPT · TWO ROUTERS", "PAIRED EVALUATION · LIVE DEMO", 1)
    original = original.replace("Portal → AMX ON / OFF SR → LiteLLM → vLLM。只選擇既有服務，不切換主機 AMX 設定。",
                                "100 題：Portal → SR eval（無 GPU）。單題：Portal → SR → LiteLLM → vLLM。兩者均不切換主機 AMX 設定。", 1)
    original = original.replace('</head>', '<script src="/compare/batch.js" defer></script></head>', 1)
    original = original.replace('<form id="compare-form"', (ROOT / "batch_fragment.html").read_text() + '<section id="single-view" hidden><form id="compare-form"', 1)
    return original.replace('</main>', '</section></main>', 1)


class BatchHandler(single.CompareHandler):
    def do_GET(self):
        if self.requestline.split()[1] != self.path:
            return super().do_GET()
        if self.path in ("/compare/", "/compare/batch.js"):
            body = comparison_html().encode() if self.path == "/compare/" else (ROOT / "batch.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if self.path == "/compare/" else "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/compare/batch/info":
            try:
                data = corpus()
                result = {"available": True, "count": len(data["prompts"]), "warmups": len(data["warmups"]),
                          "corpus_sha256": CORPUS_SHA, "round_options": [1, 3, 5], "default_rounds": 3,
                          "protocol": protocol(3)}
                return self._send_amx_json(200, result)
            except Exception:
                return self._send_amx_json(503, {"available": False, "error": "題庫目前無法驗證，批次功能未啟動。"})
        match = re.fullmatch(r"/api/compare/batch/([0-9a-f]{32})", self.path)
        if match:
            data = snapshot(match[1], heartbeat=True)
            return self._send_amx_json(200 if data else 404, data or {"error": "run 不存在或已過期；不會自動重跑。"})
        return super().do_GET()

    def do_POST(self):
        cancel = re.fullmatch(r"/api/compare/batch/([0-9a-f]{32})/cancel", self.path)
        if self.path != "/api/compare/batch/start" and not cancel:
            return super().do_POST()
        self.close_connection = True
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")):
            return self._send_amx_json(403, {"error": "same-origin requests only"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self._send_amx_json(415, {"error": "JSON required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 1024:
                raise ValueError()
            self.connection.settimeout(10)
            body = json.loads(self.rfile.read(length))
            if cancel:
                if body != {}:
                    raise ValueError()
                with JOB_LOCK:
                    job = JOBS.get(cancel[1])
                    if job is None:
                        return self._send_amx_json(404, {"error": "run 不存在"})
                    job["cancel"].set()
                return self._send_amx_json(202, {"cancel_requested": True})
            if (not isinstance(body, dict) or set(body) != {"run_id", "rounds", "acknowledge_load"}
                    or not isinstance(body["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", body["run_id"])
                    or type(body["rounds"]) is not int or body["rounds"] not in (1, 3, 5)
                    or body["acknowledge_load"] is not True):
                raise ValueError()
        except Exception:
            return self._send_amx_json(400, {"error": "需有效 run ID、1/3/5 輪及負載確認；不能傳入自訂 URL 或題目。"})
        code, data = start_job(body["run_id"], body["rounds"])
        self._send_amx_json(code, data)


portal.Handler = BatchHandler

if __name__ == "__main__":
    portal.main()