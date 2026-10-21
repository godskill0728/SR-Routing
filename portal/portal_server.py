#!/usr/bin/env python3
"""vLLM Semantic Router Portal.

A zero-dependency (stdlib only) web portal that lets a user type a prompt and
watch, in real time:
  * the complexity classification (easy / medium / hard)
  * which routing decision fired and which vLLM backend was chosen
  * the model's streamed "thinking" (reasoning) and final answer

The backend proxies to the Semantic Router's Envoy entrypoint, captures the
``x-vsr-*`` routing headers, and streams everything back to the browser over SSE.

The ``max_tokens`` foot-gun (reasoning models spending the whole budget on the
thinking phase and returning ``content: null``) is handled here: we default to a
generous budget so the final answer always has room.
"""

import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ENVOY_URL = os.environ.get("ENVOY_URL", "http://127.0.0.1:9").rstrip("/")
# Fixed server-owned destinations, never a client-supplied URL or global mode.
CHAT_TARGETS = {
  "on": os.environ.get("ENVOY_URL_ON", ENVOY_URL).rstrip("/"),
  "off": os.environ.get("ENVOY_URL_OFF", "http://127.0.0.1:9").rstrip("/"),
}
ROUTER_HEALTH_URLS = {
  "on": os.environ.get("ROUTER_HEALTH_URL_ON", "http://127.0.0.1:9/health"),
  "off": os.environ.get("ROUTER_HEALTH_URL_OFF", "http://127.0.0.1:9/health"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self, req, fp, code, msg, headers, newurl):
    return None


INTERNAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
HEALTH_LOCK = threading.Lock()
HEALTH_CACHE = {"expires": 0.0, "data": None}


def dual_router_status():
  """Bounded, cached SR health checks only; not kernel or GPU verification."""
  with HEALTH_LOCK:
    if HEALTH_CACHE["data"] is not None and time.monotonic() < HEALTH_CACHE["expires"]:
      return HEALTH_CACHE["data"]
    services = {}
    for mode, url in ROUTER_HEALTH_URLS.items():
      try:
        with INTERNAL_HTTP.open(url, timeout=2) as response:
          reachable = response.status == 200
      except Exception:
        reachable = False
      services[mode] = {"router_reachable": reachable}
    data = {"services": services, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    HEALTH_CACHE.update(data=data, expires=time.monotonic() + 5)
    return data


DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "99999"))
MIN_MAX_TOKENS = int(os.environ.get("MIN_MAX_TOKENS", "512"))
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
AMX_CONTROL_SOCKET = os.environ.get("AMX_CONTROL_SOCKET", "/run/sr-amx/control.sock")
AMX_TIMEOUT = 10
AMX_MAX_BODY = 4096
AMX_MAX_RESPONSE = 65536

# Exact request targets only: never decode/normalize user paths or serve a directory.
# ConfigMap filenames are constants, not derived from request input.
REPORTS_ROOT = Path(os.environ.get("REPORTS_ROOT", str(Path(__file__).resolve().parent.parent / "reports-public")))
REPORT_ROUTES = {
  "/reports/": ("index.html", "text/html; charset=utf-8"),
  "/reports/capacity/": ("capacity.html", "text/html; charset=utf-8"),
  "/reports/capacity/summary.csv": ("capacity-summary.csv", "text/csv; charset=utf-8"),
  "/reports/capacity/rounds.csv": ("capacity-rounds.csv", "text/csv; charset=utf-8"),
  "/reports/benchmark-100/": ("benchmark-100.html", "text/html; charset=utf-8"),
  "/reports/benchmark-concurrency/": ("benchmark-concurrency.html", "text/html; charset=utf-8"),
  "/reports/retest/": ("retest.html", "text/html; charset=utf-8"),
  "/reports/retest/summary.csv": ("retest-summary.csv", "text/csv; charset=utf-8"),
  "/reports/sweep/": ("sweep.html", "text/html; charset=utf-8"),
  "/reports/sweep/summary.csv": ("sweep-summary.csv", "text/csv; charset=utf-8"),
  "/reports/sweep/rounds.csv": ("sweep-rounds.csv", "text/csv; charset=utf-8"),
  "/reports/corpus/": ("corpus.html", "text/html; charset=utf-8"),
  "/reports/corpus/corpus.json": ("corpus.json", "application/json; charset=utf-8"),
  "/reports/benchmark-100/summary.csv": ("benchmark-100-summary.csv", "text/csv; charset=utf-8"),
  "/reports/benchmark-100/comparison.csv": ("benchmark-100-comparison.csv", "text/csv; charset=utf-8"),
  "/reports/benchmark-100/paired-comparison.csv": ("benchmark-100-paired-comparison.csv", "text/csv; charset=utf-8"),
  "/reports/benchmark-concurrency/summary.csv": ("benchmark-concurrency-summary.csv", "text/csv; charset=utf-8"),
  "/reports/benchmark-concurrency/paired-comparison.csv": ("benchmark-concurrency-paired-comparison.csv", "text/csv; charset=utf-8"),
}

VSR_HEADERS = [
    "x-vsr-matched-complexity",
    "x-vsr-selected-decision",
    "x-vsr-selected-model",
    "x-vsr-selected-confidence",
    "x-vsr-selected-reasoning",
    "x-vsr-injected-system-prompt",
    "x-vsr-context-token-count",
    "x-vsr-response-path",
]


def sse(event, data):
    """Encode one Server-Sent Event frame."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


class AMXConnection(http.client.HTTPConnection):
  """HTTP over a fixed Unix socket: no TCP fallback, shell, or cluster access."""

  def __init__(self):
    super().__init__("localhost", timeout=AMX_TIMEOUT)

  def connect(self):
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.sock.settimeout(AMX_TIMEOUT)
    self.sock.connect(AMX_CONTROL_SOCKET)


def amx_public_status(data):
  """Validate public evidence; never expose arbitrary controller log fields."""
  if not isinstance(data, dict):
    raise ValueError("invalid status")
  if (type(data.get("busy")) is not bool
      or data.get("target") not in (None, "on", "off")
      or data.get("phase") not in ("idle", "running", "succeeded", "failed")
      or not isinstance(data.get("updated_at"), str)
      or not all(data.get(key) is None or isinstance(data[key], str)
             for key in ("requested_mode", "error"))):
    raise ValueError("invalid status")
  evidence = data.get("evidence")
  if evidence is not None:
    if (not isinstance(evidence, dict)
        or evidence.get("mode") not in ("on", "off")
        or not all(isinstance(evidence.get(key), str)
               for key in ("backend", "precision"))
        or not all(type(evidence.get(key)) is int and evidence[key] >= 0
               for key in ("amx_nodes", "executed_nodes"))):
      raise ValueError("invalid evidence")
    evidence = {key: evidence[key] for key in
          ("mode", "backend", "precision", "amx_nodes", "executed_nodes")}
  return {
    "busy": data["busy"], "target": data.get("target"), "phase": data["phase"],
    "evidence": evidence, "requested_mode": data.get("requested_mode"),
    # Controller errors can contain internal logs. Do not relay them or secrets.
    "error": "切換失敗；請管理員檢查主機端記錄與回復狀態。" if data.get("error") else None,
    "updated_at": data["updated_at"],
  }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quieter logs
        pass

    # ---- routing -----------------------------------------------------------
    def do_GET(self):
      if self.requestline.split()[1] != self.path:
        # BaseHTTPRequestHandler collapses a leading //; reject aliases too.
        self._send_text(404, "not found")
      elif self.path in REPORT_ROUTES:
        self._get_report()
      elif self.path in ("/", "/index.html"):
        body = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
      elif self.path == "/healthz":
        self._send_text(200, "ok")
      elif self.path == "/api/amx/status":
        self._proxy_amx("GET")
      elif self.path == "/api/routers/status":
        self._send_amx_json(200, dual_router_status())
      else:
        self._send_text(404, "not found")

    def do_POST(self):
        if self.path == "/api/amx":
          self._post_amx()
          return
        if self.path != "/api/stream":
          # Do not interpret an unread rejected POST body as another request.
          self.close_connection = True
          self._send_text(404, "not found")
          return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send_text(400, f"bad request: {exc}")
            return

        if not isinstance(req, dict) or not isinstance(req.get("prompt"), str):
          self._send_text(400, "prompt must be a string")
          return
        mode = req.get("amx_mode", "on")
        if mode not in ("on", "off"):
          self._send_text(400, "amx_mode must be on or off")
          return
        prompt = req["prompt"].strip()
        if not prompt:
            self._send_text(400, "empty prompt")
            return
        try:
            max_tokens = int(req.get("max_tokens") or DEFAULT_MAX_TOKENS)
        except (TypeError, ValueError):
            max_tokens = DEFAULT_MAX_TOKENS
        # Guard against the reasoning-model foot-gun: never let the budget be so
        # small that the thinking phase eats it all and content comes back null.
        max_tokens = max(max_tokens, MIN_MAX_TOKENS)

        self._open_sse()
        try:
            self._emit(sse("target", {"amx_mode": mode}))
            self._proxy_stream(prompt, max_tokens, mode)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            self._emit(sse("error", {"message": f"upstream {exc.code}", "detail": detail}))
        except Exception as exc:  # noqa: BLE001
            self._emit(sse("error", {"message": str(exc)}))
        finally:
            try:
                self._emit(b"event: end\ndata: {}\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _get_report(self):
      filename, mime = REPORT_ROUTES[self.path]
      try:
        root = REPORTS_ROOT.resolve(strict=True)
        target = (root / filename).resolve(strict=True)
        # ConfigMap atomic symlinks stay inside this one read-only volume.
        target.relative_to(root)
        if not target.is_file() or target.stat().st_size > 900_000:
          raise ValueError("invalid report artifact")
        body = target.read_bytes()
      except (OSError, ValueError, RuntimeError):
        self._send_text(404, "not found")
        return
      self.send_response(200)
      self.send_header("Content-Type", mime)
      self.send_header("Content-Length", str(len(body)))
      self.send_header("Cache-Control", "no-cache")
      self.send_header("X-Content-Type-Options", "nosniff")
      self.send_header("Referrer-Policy", "no-referrer")
      self.send_header("Content-Security-Policy",
               "default-src 'none'; style-src 'unsafe-inline'; "
               "script-src 'unsafe-inline'; img-src data:; "
               "connect-src 'none'; base-uri 'none'; form-action 'none'; "
               "frame-ancestors 'none'; sandbox allow-scripts allow-downloads")
      self.end_headers()
      self.wfile.write(body)

    # ---- AMX controller proxy (independent of chat) -------------------------
    def _post_amx(self):
      if os.environ.get("ENABLE_AMX_CONTROL") != "true":
        return self._send_amx_json(403, {"error": "AMX management is disabled in this portable demo."})
      # Close every AMX response, including rejections with unread request bytes.
      # Reject ambiguous framing and headers before reading or forwarding data.
      if any(len(self.headers.get_all(key, [])) > 1 for key in (
          "Host", "Origin", "Sec-Fetch-Site", "Content-Type",
          "Content-Length", "Authorization")):
        self._send_amx_json(400, {"error": "Ambiguous request headers."})
        return
      origin = self.headers.get("Origin")
      try:
        same_origin = origin is None or (
          urllib.parse.urlsplit(origin).scheme in ("http", "https")
          and urllib.parse.urlsplit(origin).netloc == self.headers.get("Host")
        )
      except ValueError:
        same_origin = False
      if (not same_origin
          or self.headers.get("Sec-Fetch-Site", "").strip().lower() == "cross-site"):
        self._send_amx_json(403, {"error": "Cross-site requests are not allowed."})
        return
      if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        self._send_amx_json(415, {"error": "Content-Type must be application/json."})
        return
      if self.headers.get_all("Transfer-Encoding"):
        self._send_amx_json(400, {"error": "Transfer-Encoding is not supported."})
        return
      length_header = self.headers.get("Content-Length")
      if length_header is None:
        self._send_amx_json(411, {"error": "Content-Length is required."})
        return
      if not re.fullmatch(r"[0-9]+", length_header) or len(length_header) > 10:
        self._send_amx_json(400, {"error": "Invalid Content-Length."})
        return
      length = int(length_header)
      if length > AMX_MAX_BODY:
        self._send_amx_json(413, {"error": "JSON body must not exceed 4 KB."})
        return
      try:
        self.connection.settimeout(AMX_TIMEOUT)
        raw = self.rfile.read(length)
        if len(raw) != length:
          raise ValueError("incomplete body")
        data = json.loads(raw.decode("utf-8"))
      except (ValueError, OSError, RecursionError):
        self._send_amx_json(400, {"error": "Invalid or incomplete JSON body."})
        return
      if not isinstance(data, dict) or data.get("mode") not in ("on", "off"):
        self._send_amx_json(400, {"error": "mode must be on or off."})
        return
      authorization = self.headers.get("Authorization", "")
      if not re.fullmatch(r"Bearer [A-Za-z0-9._~+/-]+=*", authorization, re.IGNORECASE):
        self._send_amx_json(401, {"error": "A valid manager Bearer token is required."})
        return
      self._proxy_amx("POST", {"mode": data["mode"]}, authorization)

    def _proxy_amx(self, method, payload=None, authorization=None):
      conn = AMXConnection()
      try:
        headers = {"Accept": "application/json", "Connection": "close"}
        body = None
        if method == "POST":
          headers["Content-Type"] = "application/json"
          headers["Authorization"] = authorization
          body = json.dumps(payload).encode("utf-8")
        conn.request(method, "/status" if method == "GET" else "/mode",
               body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read(AMX_MAX_RESPONSE + 1)
        if len(raw) > AMX_MAX_RESPONSE:
          raise ValueError("oversized controller response")
        if method == "GET":
          if (response.status != 200
              or response.headers.get_content_type() != "application/json"):
            raise ValueError("controller unavailable")
          result = amx_public_status(json.loads(raw.decode("utf-8")))
          code = 200
        else:
          # Never echo mutation response bodies, authorization, or exceptions.
          # 202 is acceptance only, not evidence that the switch succeeded.
          code = response.status
          results = {
            202: {"accepted": True},
            400: {"error": "Invalid AMX mode."},
            401: {"error": "Invalid manager token."},
            409: {"error": "An AMX change is already running."},
          }
          if code not in results:
            raise ValueError("controller unavailable")
          result = results[code]
      except Exception:  # Transport, timeout, malformed response: fail closed.
        code, result = 503, {"error": "AMX controller unavailable; check status before retrying."}
      finally:
        conn.close()
      self._send_amx_json(code, result)

    def _send_amx_json(self, code, data):
      body = json.dumps(data, ensure_ascii=False).encode("utf-8")
      self.close_connection = True
      self.send_response(code)
      self.send_header("Content-Type", "application/json; charset=utf-8")
      self.send_header("Content-Length", str(len(body)))
      self.send_header("Cache-Control", "no-store")
      self.send_header("X-Content-Type-Options", "nosniff")
      self.send_header("Connection", "close")
      self.end_headers()
      self.wfile.write(body)

    # ---- upstream proxy ----------------------------------------------------
    def _open_upstream(self, prompt, max_tokens, mode="on"):
        """Open the upstream stream, retrying transient 5xx before any data flows.

        The semantic router occasionally returns a 500 on the very first
        request (cold ext_proc path); retrying a few times makes the portal
        resilient to that without the user noticing.
        """
        payload = {
            "model": "auto",
            "stream": True,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = json.dumps(payload).encode("utf-8")
        last_exc = None
        for attempt in range(4):
            req = urllib.request.Request(
                f"{CHAT_TARGETS[mode]}/v1/chat/completions",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                return INTERNAL_HTTP.open(req, timeout=300)
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code >= 500 and attempt < 3:
                    self._emit(sse("status", {"message": f"upstream {exc.code}, retrying ({attempt + 1}/3)…"}))
                    continue
                raise
        raise last_exc  # pragma: no cover

    def _proxy_stream(self, prompt, max_tokens, mode="on"):
      with self._open_upstream(prompt, max_tokens, mode) as resp:
        self._relay_stream(resp, max_tokens, mode)

    def _relay_stream(self, resp, max_tokens, mode):

        # 1) Surface the routing metadata as soon as headers arrive.
        meta = {h: resp.headers.get(h) for h in VSR_HEADERS}
        meta["max_tokens"] = max_tokens
        meta["amx_mode"] = mode
        self._emit(sse("meta", meta))

        # 2) Relay the token stream, splitting reasoning vs. final answer.
        finish_reason = None
        usage = None
        backend_model = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            backend_model = obj.get("model") or backend_model
            if obj.get("usage"):
                usage = obj["usage"]
            for choice in obj.get("choices", []):
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning:
                    self._emit(sse("reasoning", {"text": reasoning}))
                if content:
                    self._emit(sse("content", {"text": content}))
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        self._emit(sse("done", {
            "finish_reason": finish_reason,
            "usage": usage,
            "backend_model": backend_model,
        }))

    # ---- low level helpers -------------------------------------------------
    def _open_sse(self):
        # No Content-Length / chunked framing is used for the SSE body, so the
        # connection MUST be closed when the stream ends. Without this the
        # browser's reader never receives `done`, and the portal's send button
        # stays disabled after the answer completes.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

    def _emit(self, frame):
        try:
            self.wfile.write(frame)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    def _send_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>vLLM Semantic Router · Portal</title>
<style>
  :root {
    --bg:#f5f7fb; --panel:#ffffff; --panel2:#f0f3f9; --line:#dfe4ee;
    --txt:#1a2233; --muted:#5c6b86; --accent:#3366ff;
    --easy:#12a06e; --medium:#d98a1f; --hard:#e0435a;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI",system-ui,-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;
         background:radial-gradient(1200px 600px at 70% -10%,#e8eefc,transparent),var(--bg); color:var(--txt); }
  header { padding:18px 28px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:14px; }
  header h1 { font-size:18px; margin:0; font-weight:650; letter-spacing:.3px; }
  header .sub { color:var(--muted); font-size:13px; }
  .wrap { max-width:1080px; margin:0 auto; padding:24px 28px 60px; }
  .amx-card { background:linear-gradient(125deg,#fff 70%,#f1f6ff); border:1px solid var(--line);
              border-radius:18px; padding:22px; margin-bottom:20px; box-shadow:0 8px 28px #243e7410; }
  .amx-heading { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .amx-icon { display:grid; place-items:center; width:52px; height:52px; border-radius:14px;
              background:#eaf0ff; color:var(--accent); font-weight:800; letter-spacing:1px; }
  .amx-heading h2 { margin:3px 0; font-size:20px; }
  .amx-kicker { font-size:11px; letter-spacing:1.5px; color:var(--muted); font-weight:700; }
  .amx-state { margin-left:auto; padding:8px 15px; border-radius:999px; background:#edf0f5;
               color:#526078; font-size:14px; font-weight:750; }
  .amx-state[data-mode=on] { background:#e4f7ee; color:#08784e; }
  .amx-state[data-mode=off] { background:#eef2f8; color:#40516d; }
  .amx-copy { font-size:13px; color:var(--muted); line-height:1.7; margin:12px 0; }
  .amx-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:16px 0; }
  .amx-metrics > div { background:#f7f9fc; border:1px solid #e9edf5; border-radius:11px; padding:12px; }
  .amx-metrics dt { font-size:12px; color:var(--muted); }
  .amx-metrics dd { margin:6px 0 0; font-weight:700; font-size:16px; overflow-wrap:anywhere; }
  .amx-actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
  .amx-actions button { background:#fff; color:#354563; border:1px solid #cbd5e6; }
  .amx-actions button[aria-pressed=true] { background:#ebf1ff; border-color:var(--accent); color:#2451d6;
                                         box-shadow:0 0 0 1px var(--accent) inset; }
  .amx-actions button:not(:disabled):hover { background:#f0f5ff; }
  .amx-card :is(button,input,summary):focus-visible { outline:3px solid #85a5ff; outline-offset:3px; }
  .service-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:18px 0; }
  .service-tile { border:1px solid var(--line); background:#f7f9fc; padding:16px; border-radius:12px; }
  .service-tile h3 { margin:0 0 8px; font-size:15px; }
  .service-tile p { margin:6px 0; font-size:13px; color:var(--muted); }
  .service-tile[data-selected=true] { border-color:var(--accent); background:#eff4ff; }
  .service-health { font-weight:650; color:var(--muted); font-size:13px; }
  .service-health[data-health=ok] { color:#08784e; }
  .service-health[data-health=error] { color:#a5273e; }
  .request-target { font-weight:650; color:#2451d6; margin:12px 0 0; font-size:13px; }
  .amx-notice { font-size:13px; line-height:1.7; overflow-wrap:anywhere; margin:12px 0 0;
                border-left:3px solid #9cb8f8; padding-left:10px; }
  .amx-notice[data-kind=error] { border-color:#df6879; color:#a5273e; }
  .amx-progress { width:100%; height:6px; accent-color:var(--accent); margin-top:12px; }
  .amx-updated { color:var(--muted); font-size:12px; margin:10px 0 0; }
  @media (max-width:600px) { .amx-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
    header { flex-wrap:wrap; padding:16px; } .wrap { padding:20px 16px 40px; }
    .service-grid { grid-template-columns:1fr; }
    .amx-card { padding:16px; } .amx-actions button { flex:1; } .amx-state { margin-left:0; } }
  .composer { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; }
  textarea { width:100%; min-height:88px; resize:vertical; background:var(--panel2); color:var(--txt);
             border:1px solid var(--line); border-radius:10px; padding:12px 14px; font-size:15px; outline:none; }
  textarea:focus { border-color:var(--accent); }
  .row { display:flex; align-items:center; gap:16px; margin-top:12px; flex-wrap:wrap; }
  .row .grow { flex:1; }
  label.tok { color:var(--muted); font-size:13px; display:flex; align-items:center; gap:8px; }
  input[type=number] { width:96px; background:var(--panel2); color:var(--txt); border:1px solid var(--line);
                       border-radius:8px; padding:7px 9px; font-size:14px; }
  button { background:var(--accent); color:#fff; border:none; border-radius:10px; padding:10px 20px;
           font-size:14px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .samples { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
  .chip { background:var(--panel2); border:1px solid var(--line); color:var(--muted); border-radius:999px;
          padding:5px 12px; font-size:12.5px; cursor:pointer; }
  .chip:hover { color:var(--txt); border-color:var(--accent); }

  .pipeline { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:22px 0 8px; }
  .step { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px 14px; position:relative; opacity:.45; transition:.25s; }
  .step.active { opacity:1; border-color:var(--accent); box-shadow:0 0 0 1px var(--accent) inset; }
  .step.done { opacity:1; }
  .step .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.6px; }
  .step .v { font-size:15px; font-weight:600; margin-top:6px; min-height:20px; }

  .badge { display:inline-block; padding:3px 11px; border-radius:999px; font-size:13px; font-weight:700; }
  .badge.easy { background:rgba(39,192,138,.16); color:var(--easy); }
  .badge.medium { background:rgba(240,169,59,.16); color:var(--medium); }
  .badge.hard { background:rgba(239,91,107,.16); color:var(--hard); }
  .badge.idle { background:#e4e8f0; color:var(--muted); }

  .cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:14px; }
  @media (max-width:820px){ .cols{ grid-template-columns:1fr; } .pipeline{ grid-template-columns:1fr 1fr; } }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; overflow:hidden; }
  .card h3 { margin:0; padding:12px 16px; font-size:13.5px; border-bottom:1px solid var(--line);
             display:flex; align-items:center; gap:8px; color:var(--muted); font-weight:600; }
  .card .body { padding:14px 16px; font-size:14.5px; line-height:1.6; white-space:pre-wrap; word-break:break-word;
                min-height:120px; max-height:48vh; overflow:auto; }
  .think .body { color:#4a5875; font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace; font-size:13px; }
  .answer .body { color:var(--txt); }
  .dot { width:9px; height:9px; border-radius:50%; background:#c2ccdd; }
  .dot.live { background:var(--accent); box-shadow:0 0 0 0 var(--accent); animation:pulse 1.2s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(91,140,255,.6);} 70%{box-shadow:0 0 0 7px rgba(91,140,255,0);} 100%{box-shadow:0 0 0 0 rgba(91,140,255,0);} }
  .meta-line { color:var(--muted); font-size:12.5px; margin-top:8px; }
  .err { color:var(--hard); font-size:13px; margin-top:10px; white-space:pre-wrap; }
</style>
</head>
<body>
<header>
  <div class="dot live"></div>
  <h1>vLLM Semantic Router</h1>
  <span class="sub">輸入 prompt → 看複雜度分類、路由模型與即時思考過程</span>
  <a href="/reports/" style="color:#2451d6;font-weight:650;margin-left:auto">Benchmark reports / 語料庫 ↗</a>
</header>

<div class="wrap">
  <section class="amx-card" aria-labelledby="amx-title">
    <div role="status" aria-live="polite" aria-atomic="true">
      <div class="amx-heading">
        <div class="amx-icon" aria-hidden="true">AMX</div>
        <div><div class="amx-kicker">DUAL ROUTER · PER-REQUEST SELECTION</div><h2 id="amx-title">選擇 AMX ON / OFF 服務</h2></div>
        <span id="amx-state" class="amx-state" data-mode="on">已選 ON</span>
      </div>
      <p id="amx-status" class="amx-notice">下一筆聊天送往 AMX ON 服務；選擇不會重啟 Pod。</p>
    </div>
    <p class="amx-copy">兩組 Router 同時運行，直接選擇本次聊天的路徑，不修改另一組、不需要管理金鑰，也不影響其他使用者的選擇。AMX 僅適用於 CPU complexity embedding，不代表 GPU 生成加速。</p>
    <div class="service-grid">
      <section class="service-tile" id="service-on" data-selected="true"><h3>AMX ON · 獨立服務</h3>
        <span id="health-on" class="service-health">SR 健康：查詢中…</span>
        <p>配置：OpenVINO BF16 · AMX ISA</p></section>
      <section class="service-tile" id="service-off" data-selected="false"><h3>AMX OFF · 獨立服務</h3>
        <span id="health-off" class="service-health">SR 健康：查詢中…</span>
        <p>配置：OpenVINO BF16 · 非 AMX ISA</p></section>
    </div>
    <p class="amx-copy">SR 健康僅檢查 Router HTTP health；不是即時 kernel 驗證，也不保證 Envoy／GPU 可用。若所選路徑失敗，會顯示錯誤，不自動改送另一組。<a href="/reports/">公開示範版報表說明 ↗</a></p>
    <p id="amx-updated" class="amx-updated">每 10 秒自動查詢 SR 健康</p>
    <div class="amx-actions" role="group" aria-label="本次聊天服務">
      <button type="button" id="amx-on" aria-pressed="true">使用 AMX ON</button>
      <button type="button" id="amx-off" aria-pressed="false">使用 AMX OFF</button>
    </div>
  </section>
  <div class="composer">
    <textarea id="prompt" placeholder="輸入你的問題，例如：證明 2 的平方根是無理數..."></textarea>
    <div class="row">
      <label class="tok">max_tokens
        <input id="maxtok" type="number" min="512" max="99999" step="128" value="99999" />
        <span style="font-size:12px;color:var(--muted)">(已自動放大，避免 reasoning 模型只輸出思考)</span>
      </label>
      <div class="grow"></div>
      <button id="send">送出</button>
    </div>
    <div class="samples">
      <span class="chip" data-p="What is the capital of France?">easy · 法國首都</span>
      <span class="chip" data-p="Compare REST and GraphQL APIs and explain the trade-offs.">medium · 比較</span>
      <span class="chip" data-p="Prove that the square root of 2 is irrational, then write a thread-safe LRU cache in C++ and explain its concurrency model.">hard · 證明+並發</span>
    </div>
    <div id="err" class="err"></div>
  </div>

  <div class="pipeline">
    <div class="step" id="s1"><div class="k">1 · 分類</div><div class="v"><span id="cx" class="badge idle">待命</span></div></div>
    <div class="step" id="s2"><div class="k">2 · 路由決策</div><div class="v" id="dec">—</div></div>
    <div class="step" id="s3"><div class="k">3 · vLLM 後端</div><div class="v" id="mdl">—</div></div>
    <div class="step" id="s4"><div class="k">4 · 狀態</div><div class="v" id="stat">—</div></div>
  </div>
  <div class="meta-line" id="metaline"></div>
  <p id="request-target" class="request-target" role="status" aria-live="polite">尚未送出請求</p>

  <div class="cols">
    <div class="card think">
      <h3><span class="dot" id="thinkdot"></span> 思考過程 (reasoning)</h3>
      <div class="body" id="think"></div>
    </div>
    <div class="card answer">
      <h3><span class="dot" id="ansdot"></span> 答案 (answer)</h3>
      <div class="body" id="answer"></div>
    </div>
  </div>
</div>

<script>
const BACKENDS = {
  "qwen3.5-4b-l4": { name:"Qwen3.5-4B", gpu:"L4 GPU" },
  "gemma-4-12b":   { name:"Gemma-4-12B", gpu:"H100" },
  "qwen3.8-27b":   { name:"Qwen3.8-27B", gpu:"H100" },
};
const $ = (id) => document.getElementById(id);
const el = { prompt:$("prompt"), maxtok:$("maxtok"), send:$("send"), err:$("err"),
  cx:$("cx"), dec:$("dec"), mdl:$("mdl"), stat:$("stat"), metaline:$("metaline"),
  think:$("think"), answer:$("answer"), thinkdot:$("thinkdot"), ansdot:$("ansdot"),
  s1:$("s1"), s2:$("s2"), s3:$("s3"), s4:$("s4") };

// Page-local choice. Snapshot it for each request; never call the mode controller.
let selectedMode = "on";
let chatRunning = false;
function renderSelection() {
  $("amx-state").textContent = "已選 " + selectedMode.toUpperCase();
  $("amx-state").dataset.mode = selectedMode;
  $("amx-status").textContent = (chatRunning ? "本次聊天使用 AMX " : "下一筆聊天送往 AMX ") +
    selectedMode.toUpperCase() + (chatRunning ? "；串流結束後可重新選擇。" : " 服務；選擇不會重啟 Pod。");
  for (const mode of ["on", "off"]) {
    $("amx-" + mode).disabled = chatRunning;
    $("amx-" + mode).setAttribute("aria-pressed", String(selectedMode === mode));
    $("service-" + mode).dataset.selected = String(selectedMode === mode);
  }
}
for (const mode of ["on", "off"]) {
  $("amx-" + mode).addEventListener("click", () => {
    if (chatRunning) return;
    selectedMode = mode;
    renderSelection();
  });
}
async function pollRouters() {
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 7000);
  try {
    const response = await fetch("/api/routers/status", {
      mode:"same-origin", credentials:"omit", redirect:"error", cache:"no-store", signal:abort.signal
    });
    const data = await response.json();
    if (!response.ok || !data.services || typeof data.checked_at !== "string" ||
        !["on", "off"].every(mode => typeof data.services[mode]?.router_reachable === "boolean")) {
      throw new Error("Invalid health response");
    }
    for (const mode of ["on", "off"]) {
      const ok = data.services[mode].router_reachable;
      $("health-" + mode).textContent = ok ? "SR 健康：可連線" : "SR 健康：無法確認";
      $("health-" + mode).dataset.health = ok ? "ok" : "error";
    }
    $("amx-updated").textContent = "每 10 秒自動查詢 · 最近檢查：" + data.checked_at;
  } catch {
    for (const mode of ["on", "off"]) {
      $("health-" + mode).textContent = "SR 健康：未知";
      $("health-" + mode).dataset.health = "error";
    }
    $("amx-updated").textContent = "健康查詢失敗，稍後自動重試；不會改變你的服務選擇。";
  } finally {
    clearTimeout(timeout);
    setTimeout(pollRouters, 10000);
  }
}
renderSelection();
pollRouters();

document.querySelectorAll(".chip").forEach(c =>
  c.addEventListener("click", () => { el.prompt.value = c.dataset.p; el.prompt.focus(); }));
el.prompt.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
});
el.send.addEventListener("click", run);

function reset() {
  el.err.textContent = ""; el.think.textContent = ""; el.answer.textContent = "";
  el.cx.className = "badge idle"; el.cx.textContent = "分類中…";
  el.dec.textContent = "—"; el.mdl.textContent = "—"; el.stat.textContent = "等待路由";
  el.metaline.textContent = "";
  [el.s1,el.s2,el.s3,el.s4].forEach(s => s.className = "step");
  el.s1.classList.add("active");
  el.thinkdot.className = "dot"; el.ansdot.className = "dot";
}
function difficultyOf(matched) {
  if (!matched) return "";
  const m = String(matched).toLowerCase().match(/(easy|medium|hard)/);
  return m ? m[1] : "";
}

async function run() {
  const prompt = el.prompt.value.trim();
  if (!prompt || chatRunning) return;
  const requestMode = selectedMode;
  chatRunning = true;
  renderSelection();
  reset();
  $("request-target").textContent = "本次請求：AMX " + requestMode.toUpperCase() + " · 等待 Portal 確認路徑";
  el.send.disabled = true;
  const max_tokens = parseInt(el.maxtok.value || "2048", 10);

  try {
    const resp = await fetch("/api/stream", {
      method:"POST", headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ prompt, max_tokens, amx_mode:requestMode })
    });
    if (!resp.ok || !resp.body) { el.err.textContent = "連線失敗: HTTP " + resp.status; el.send.disabled = false; return; }

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream:true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        handleFrame(frame);
      }
    }
  } catch (e) {
    el.err.textContent = "錯誤: " + e.message;
  } finally {
    chatRunning = false;
    renderSelection();
    el.send.disabled = false;
    el.thinkdot.className = "dot"; el.ansdot.className = "dot";
  }
}

function handleFrame(frame) {
  let ev = "message", data = "";
  frame.split("\n").forEach(l => {
    if (l.startsWith("event:")) ev = l.slice(6).trim();
    else if (l.startsWith("data:")) data += l.slice(5).trim();
  });
  if (!data) return;
  let obj; try { obj = JSON.parse(data); } catch { return; }

  if (ev === "target") {
    $("request-target").textContent = "本次請求：AMX " + String(obj.amx_mode).toUpperCase() + " · Portal 已選定服務路徑（非 kernel 驗證）";
    return;
  }
  if (ev === "status") {
    el.stat.textContent = obj.message || "…";
    return;
  }
  if (ev === "meta") {
    const diff = difficultyOf(obj["x-vsr-matched-complexity"]) || difficultyOf(obj["x-vsr-selected-decision"]);
    el.cx.className = "badge " + (diff || "idle");
    el.cx.textContent = diff ? diff.toUpperCase() : (obj["x-vsr-selected-decision"] || "—");
    el.s1.classList.add("done");
    el.s2.classList.add("active","done");
    el.dec.textContent = obj["x-vsr-selected-decision"] || "—";
    const key = obj["x-vsr-selected-model"];
    const b = BACKENDS[key];
    el.s3.classList.add("active","done");
    el.mdl.textContent = b ? b.name + " · " + b.gpu : (key || "—");
    el.s4.classList.add("active");
    el.stat.textContent = "生成中…";
    el.thinkdot.className = "dot live";
    const conf = obj["x-vsr-selected-confidence"];
    const reasoning = obj["x-vsr-selected-reasoning"];
    el.metaline.textContent =
      "AMX " + String(obj.amx_mode).toUpperCase() + " · 信心度 " + (conf ? (parseFloat(conf)*100).toFixed(1)+"%" : "—") +
      " · reasoning=" + (reasoning || "—") +
      " · 後端 " + (key || "—") +
      " · max_tokens=" + obj["max_tokens"];
  } else if (ev === "reasoning") {
    el.think.textContent += obj.text;
    el.think.scrollTop = el.think.scrollHeight;
  } else if (ev === "content") {
    if (el.ansdot.className !== "dot live") {
      el.ansdot.className = "dot live"; el.thinkdot.className = "dot";
    }
    el.answer.textContent += obj.text;
    el.answer.scrollTop = el.answer.scrollHeight;
  } else if (ev === "done") {
    el.s4.classList.add("done");
    const u = obj.usage || {};
    const tok = u.completion_tokens != null ? (u.completion_tokens + " tokens") : "";
    el.stat.textContent = "完成";
    if (obj.finish_reason === "length") {
      el.stat.textContent = "完成 (達 max_tokens)";
    }
    el.metaline.textContent += tok ? "  ·  輸出 " + tok : "";
  } else if (ev === "error") {
    el.err.textContent = "上游錯誤: " + (obj.message || "") + (obj.detail ? "\n" + obj.detail : "");
    el.stat.textContent = "失敗";
  }
}
</script>
</body>
</html>
"""


def main():
    server = ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), LISTEN_PORT), Handler)
    print(f"portal listening on :{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
