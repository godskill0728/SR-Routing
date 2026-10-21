"""Additive Portal comparison; no router reconfiguration or inference retries."""
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import litellm_portal_release  # installs the portable, sanitized report allowlists
import portal_server as portal

ROOT = Path(__file__).resolve().parent
JAEGER = os.environ.get("JAEGER_TRACE_URL", "http://127.0.0.1:9/api/traces/").rstrip("/") + "/"
SLOTS = threading.BoundedSemaphore(4)
LOCK = threading.Lock()
RUNS = {}
TTL = 600
BASE_HANDLER = portal.Handler


def trace_timing(document, trace_id, mode):
    """Jaeger timestamps/durations are microseconds. Never sum overlapping spans."""
    service = os.environ.get("TRACE_SERVICE_" + mode.upper(), "sr-demo-" + mode)
    traces = [t for t in document.get("data", []) if t.get("traceID") == trace_id]
    if len(traces) != 1:
        return None
    trace = traces[0]
    processes = trace.get("processes", {})
    spans = [s for s in trace.get("spans", [])
             if processes.get(s.get("processID"), {}).get("serviceName") == service]
    signals = [s for s in spans if s.get("operationName") == "semantic_router.signal.evaluation"]
    upstreams = [s for s in spans if s.get("operationName") == "semantic_router.upstream.request"]
    if len(signals) != 1 or len(upstreams) != 1:
        return None
    signal, upstream = signals[0], upstreams[0]
    # Require the upstream span to descend from this signal, not another branch.
    by_id = {s.get("spanID"): s for s in spans}
    current, visited = upstream, set()
    while current.get("spanID") != signal.get("spanID"):
        sid = current.get("spanID")
        if not sid or sid in visited:
            return None
        visited.add(sid)
        refs = [r for r in current.get("references", [])
                if r.get("refType") == "CHILD_OF" and r.get("traceID") == trace_id]
        if len(refs) != 1 or refs[0].get("spanID") not in by_id:
            return None
        current = by_id[refs[0]["spanID"]]
    start, duration, end = signal.get("startTime"), signal.get("duration"), upstream.get("startTime")
    if not all(type(v) is int and v >= 0 for v in (start, duration, end)):
        return None
    if not 0 <= duration <= end - start <= 300_000_000:
        return None
    return {"routing_stage_seconds": (end - start) / 1_000_000,
            "signal_seconds": duration / 1_000_000,
            "source": "Jaeger: signal.evaluation start → upstream.request start"}


def register_run(mode):
    now = time.monotonic()
    with LOCK:
        for key in list(RUNS):
            if now - RUNS[key]["created"] > TTL:
                del RUNS[key]
        if len(RUNS) >= 256:
            return None
        token = secrets.token_hex(16)
        entry = {"trace_id": secrets.token_hex(16), "mode": mode, "created": now,
                 "last_check": -100.0, "result": None, "checking": False}
        RUNS[token] = entry
        return token, entry


class CompareHandler(BASE_HANDLER):
    def do_GET(self):
        if self.requestline.split()[1] != self.path:
            return super().do_GET()
        if self.path in ("/compare/", "/compare/demo.js"):
            filename, mime = ("compare.html", "text/html; charset=utf-8") if self.path == "/compare/" else ("demo.js", "text/javascript; charset=utf-8")
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)
            return
        match = re.fullmatch(r"/api/compare/timing/([0-9a-f]{32})", self.path)
        if match:
            return self._timing(match[1])
        return super().do_GET()

    def _timing(self, token):
        # Only a random capability issued by this demo can query its own trace.
        # Raw spans, prompts, arbitrary trace queries, and upstream errors are never exposed.
        with LOCK:
            entry = RUNS.get(token)
            if entry is None or time.monotonic() - entry["created"] > TTL:
                return self._send_amx_json(404, {"state": "expired"})
            if entry["result"]:
                return self._send_amx_json(200, {"state": "ready", **entry["result"]})
            check = not entry["checking"] and time.monotonic() - entry["last_check"] >= 2
            if check:
                entry.update(checking=True, last_check=time.monotonic())
        result = None
        if check:
            try:
                with portal.INTERNAL_HTTP.open(JAEGER + entry["trace_id"], timeout=3) as resp:
                    raw = resp.read(1_000_001)
                    if len(raw) <= 1_000_000:
                        result = trace_timing(json.loads(raw), entry["trace_id"], entry["mode"])
            except Exception:
                pass  # unavailable or not exported yet; never invent zero timing
            finally:
                with LOCK:
                    entry.update(checking=False, result=result)
        self._send_amx_json(200, {"state": "ready", **result} if result else {"state": "pending"})

    def do_POST(self):
        if self.path != "/api/compare/stream":
            return super().do_POST()
        self.close_connection = True
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")):
            return self._send_amx_json(403, {"error": "same-origin requests only"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self._send_amx_json(415, {"error": "JSON with Content-Length required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 32768:
                raise ValueError()
            self.connection.settimeout(10)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"prompt", "amx_mode", "max_tokens"}:
                raise ValueError()
            prompt, mode, tokens = body["prompt"], body["amx_mode"], body["max_tokens"]
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
                raise ValueError()
            if mode not in ("on", "off") or type(tokens) is not int or not 64 <= tokens <= 1024:
                raise ValueError()
        except Exception:
            return self._send_amx_json(400, {"error": "prompt: 1–8000 chars; mode: on/off; max_tokens: 64–1024"})
        if not SLOTS.acquire(blocking=False):
            return self._send_amx_json(429, {"error": "Demo busy; try again after the current comparison."})
        opened = False
        try:
            run = register_run(mode)
            if run is None:
                return self._send_amx_json(429, {"error": "Demo request limit reached; try again later."})
            token, entry = run
            self._open_sse()
            opened = True
            self._emit(portal.sse("target", {"amx_mode": mode, "trace_id": entry["trace_id"], "timing_token": token}))
            payload = {"model": "auto", "stream": True, "max_tokens": tokens,
                       "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
                       "messages": [{"role": "user", "content": prompt.strip()}]}
            request = urllib.request.Request(portal.CHAT_TARGETS[mode] + "/v1/chat/completions",
                data=json.dumps(payload).encode(), method="POST",
                headers={"Content-Type": "application/json",
                         "traceparent": "00-" + entry["trace_id"] + "-" + secrets.token_hex(8) + "-01"})
            # ONE upstream request, never a hidden retry that biases demo timings.
            started = time.monotonic()
            with portal.INTERNAL_HTTP.open(request, timeout=120) as resp:
                self._emit(portal.sse("headers_timing", {"seconds": time.monotonic() - started}))
                self._relay_stream(resp, tokens, mode)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            try:
                self._emit(portal.sse("error", {"message": "此側上游請求失敗或逾時；沒有自動重送。請使用 Trace ID 排查。"}))
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            SLOTS.release()
            if opened:
                try:
                    self._emit(portal.sse("end", {}))
                except (BrokenPipeError, ConnectionResetError):
                    pass


anchor = "</header>"
if portal.INDEX_HTML.count(anchor) != 1:
    raise RuntimeError("Portal navigation anchor drift")
portal.INDEX_HTML = portal.INDEX_HTML.replace(anchor,
    '<a href="/compare/" style="margin-left:auto;color:#2451d6;font-weight:700;text-decoration:none">AMX ON / OFF 比較 ↗</a>' + anchor, 1)
portal.Handler = CompareHandler

if __name__ == "__main__":
    portal.main()