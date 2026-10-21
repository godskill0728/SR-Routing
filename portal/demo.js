"use strict";
const $ = id => document.getElementById(id);
const modes = ["on", "off"];
let generation = 0, running = false, controllers = [], states = {};
const examples = {
  easy: "What is the capital of France? Answer in one sentence.",
  medium: "Compare SQL and NoSQL databases. Explain their trade-offs and when to use each.",
  hard: "Design a distributed transaction protocol across three regions. Explain its consistency guarantees, failure recovery and latency trade-offs."
};
const seconds = value => Number.isFinite(value) ? value.toFixed(3) + " s" : "—";
for (const mode of modes) {
  const article = document.createElement("article");
  article.className = "panel " + mode;
  article.setAttribute("aria-label", "AMX " + mode.toUpperCase());
  // Only fixed mode constants are interpolated. Model output is always textContent.
  article.innerHTML = `<div class="panelhead"><h2>AMX ${mode.toUpperCase()}</h2><span class="badge" id="${mode}-status">待命</span></div>
    <div class="hero"><div class="label">SR 路由階段 · Trace 區間</div><div class="value" id="${mode}-routing">—</div><div class="hint">訊號評估開始 → 上游呼叫開始</div></div>
    <div class="timing"><div class="metric"><span>訊號評估 · Trace</span><b id="${mode}-signal">—</b></div><div class="metric"><span>完整回應 · 瀏覽器</span><b id="${mode}-total">—</b></div><div class="metric"><span>首段文字 · 瀏覽器</span><b id="${mode}-first">—</b></div><div class="metric"><span>已等待 · 瀏覽器</span><b id="${mode}-elapsed">—</b></div></div>
    <div class="statusline" id="${mode}-trace-status">送出後取得單筆 trace，不使用平均值。</div>
    <div class="route"><p>分類：<strong id="${mode}-complexity">—</strong></p><p>路由決策：<strong id="${mode}-decision">—</strong></p><p>SR 選中模型：<strong id="${mode}-model">—</strong></p><p>回應模型：<span id="${mode}-backend">—</span></p></div>
    <h3>回答</h3><div class="answer" id="${mode}-answer">等待送出…</div><div class="hint" id="${mode}-finish"></div>
    <details><summary>Reasoning 與追蹤資訊</summary><p>Trace ID（非 LiteLLM call ID）</p><div class="trace" id="${mode}-trace">—</div><p>LiteLLM call ID</p><div class="trace" id="${mode}-call">—</div><p id="${mode}-headers"></p><div class="reasoning" id="${mode}-reasoning"></div></details>`;
  $("panels").appendChild(article);
}
function put(mode, name, text) { $(mode + "-" + name).textContent = text; }
function reset(mode) {
  states[mode] = { started: performance.now(), first: null, done: false, failed: false, model: null, backend: null, text: "", reasoning: "" };
  for (const name of ["routing", "signal", "total", "first", "elapsed", "complexity", "decision", "model", "backend", "trace", "call"]) put(mode, name, "—");
  for (const name of ["answer", "reasoning", "finish", "headers"]) put(mode, name, "");
  put(mode, "status", "送出中");
  put(mode, "trace-status", "等待取得 trace…");
}
function updateSummary() {
  const a = states.on, b = states.off;
  if (!a || !b) return;
  const mismatch = (a.model && b.model && a.model !== b.model) || (a.backend && b.backend && a.backend !== b.backend);
  if (mismatch) $("summary").textContent = "⚠ 兩側選中或回應的模型不同；不宜直接比較總秒數。SR 計時仍為各自 trace 的實測區間。";
  else if (a.failed || b.failed) $("summary").textContent = "部分請求失敗或已停止；不計算完整回應時間或加速倍率。沒有自動重送。";
  else if (a.done && b.done) $("summary").textContent = "兩側串流已完成。Trace 秒數可能稍後補上；同時呼叫共享後端，不代表 AMX 因果加速倍率。";
  else $("summary").textContent = "同一 prompt 已並行送出。兩側各一筆請求，不自動重試。";
}
function event(mode, kind, obj) {
  const state = states[mode];
  if (kind === "target") {
    state.token = obj.timing_token; put(mode, "trace", obj.trace_id);
  } else if (kind === "headers_timing") {
    put(mode, "headers", "Portal → 上游 headers 等待：" + seconds(obj.seconds) + "（非純 routing）");
  } else if (kind === "meta") {
    state.model = obj["x-vsr-selected-model"] || null;
    put(mode, "complexity", obj["x-vsr-matched-complexity"] || "未回傳");
    put(mode, "decision", obj["x-vsr-selected-decision"] || "未回傳");
    put(mode, "model", state.model || "未回傳");
    put(mode, "call", obj["x-litellm-call-id"] || "未回傳");
    put(mode, "status", "接收中"); updateSummary();
  } else if ((kind === "content" || kind === "reasoning") && typeof obj.text === "string" && obj.text.length) {
    if (state.first === null) { state.first = (performance.now() - state.started) / 1000; put(mode, "first", seconds(state.first)); }
    const key = kind === "content" ? "text" : "reasoning";
    state[key] += obj.text;
    put(mode, kind === "content" ? "answer" : "reasoning", state[key]);
  } else if (kind === "done") {
    state.backend = obj.backend_model || null;
    put(mode, "backend", state.backend || "未回傳");
    put(mode, "finish", "finish reason: " + (obj.finish_reason || "未回傳") + (obj.finish_reason === "length" ? " · 已達 token 上限，答案可能截斷。" : ""));
    if (!obj.finish_reason) throw new Error("串流未提供 finish reason；無法確認完成。");
    state.done = true;
    put(mode, "total", seconds((performance.now() - state.started) / 1000));
    put(mode, "status", obj.finish_reason === "length" ? "完成 · token 上限" : "完成");
    if (!state.text) put(mode, "answer", "此回應没有 final content，請檢查 reasoning 與 finish reason。");
    updateSummary();
  } else if (kind === "error") throw new Error(obj.message || "上游失敗");
}
async function pollTiming(mode, token, gen, signal) {
  const deadline = performance.now() + 60000;
  while (generation === gen && !signal.aborted && performance.now() < deadline) {
    try {
      const resp = await fetch("/api/compare/timing/" + token, {signal, cache: "no-store"});
      if (!resp.ok) break;
      const data = await resp.json();
      if (generation !== gen || signal.aborted) return;
      if (data.state === "ready") {
        put(mode, "routing", seconds(data.routing_stage_seconds));
        put(mode, "signal", seconds(data.signal_seconds));
        put(mode, "trace-status", "✓ 已取得同筆請求的 Jaeger trace 計時");
        return;
      }
    } catch (err) { if (signal.aborted) return; }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (generation === gen && !signal.aborted) put(mode, "trace-status", "Trace 計時目前不可用；不是 0 秒。可用 Trace ID 稍後排查。");
}
async function send(mode, prompt, maxTokens, gen) {
  const controller = new AbortController(); controllers.push(controller);
  const clock = setInterval(() => {
    if (generation === gen && !states[mode].done) put(mode, "elapsed", seconds((performance.now() - states[mode].started) / 1000));
  }, 100);
  const timeout = setTimeout(() => controller.abort(), 120000);
  let reader;
  try {
    const resp = await fetch("/api/compare/stream", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({prompt, amx_mode: mode, max_tokens: maxTokens}), signal: controller.signal});
    if (!resp.ok) throw new Error("Portal HTTP " + resp.status + "；此側未完成，沒有自動重試。");
    if (!(resp.headers.get("content-type") || "").includes("text/event-stream")) throw new Error("不是預期的串流回應");
    reader = resp.body.getReader();
    const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const chunk = await reader.read();
      if (generation !== gen) return;
      buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        let kind = "message"; const data = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) kind = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (data.length) event(mode, kind, JSON.parse(data.join("\n")));
      }
      if (chunk.done) break;
      if (buffer.length > 1000000) throw new Error("串流格式超出限制");
    }
    if (!states[mode].done) throw new Error("串流中斷，沒有完成事件。");
  } catch (err) {
    if (generation !== gen) return;
    states[mode].failed = true;
    put(mode, "status", controller.signal.aborted ? "已停止／逾時" : "失敗");
    put(mode, "total", "—");
    put(mode, "finish", controller.signal.aborted ? "已停止接收；不保證後端立即停止。" : err.message);
    updateSummary();
  } finally {
    clearInterval(clock); clearTimeout(timeout);
    if (reader) { try { await reader.cancel(); } catch (_) {} }
    if (generation === gen) {
      put(mode, "elapsed", seconds((performance.now() - states[mode].started) / 1000));
      if (states[mode].token && !controller.signal.aborted) {
        const pollController = new AbortController(); controllers.push(pollController);
        void pollTiming(mode, states[mode].token, gen, pollController.signal);
      } else put(mode, "trace-status", "沒有取得 trace 計時，或已停止查詢。");
    }
  }
}
$("compare-form").addEventListener("submit", async e => {
  e.preventDefault(); if (running) return;
  const prompt = $("prompt").value.trim(); if (!prompt) return;
  controllers.forEach(c => c.abort()); controllers = [];
  const gen = ++generation; running = true;
  $("start").disabled = true; $("stop").disabled = false;
  $("prompt").disabled = true; $("tokens").disabled = true;
  for (const button of document.querySelectorAll("[data-example]")) button.disabled = true;
  modes.forEach(reset); updateSummary();
  await Promise.allSettled(modes.map(mode => send(mode, prompt, Number($("tokens").value), gen)));
  if (generation !== gen) return;
  running = false; $("start").disabled = false; $("stop").disabled = true;
  $("prompt").disabled = false; $("tokens").disabled = false;
  for (const button of document.querySelectorAll("[data-example]")) button.disabled = false;
});
$("stop").addEventListener("click", () => controllers.forEach(c => c.abort()));
for (const button of document.querySelectorAll("[data-example]")) button.addEventListener("click", () => { $("prompt").value = examples[button.dataset.example]; });
window.addEventListener("pagehide", () => controllers.forEach(c => c.abort()));