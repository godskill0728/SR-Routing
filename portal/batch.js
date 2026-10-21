"use strict";
(() => {
  const el = id => document.getElementById(id);
  const text = (id, value) => { el(id).textContent = value; };
  const number = x => typeof x === "number" && Number.isFinite(x);
  const secs = x => number(x) ? x.toFixed(4) + " s" : "—";
  const ratio = x => number(x) ? x.toFixed(3) + "×" : "—";
  const percent = (n, d) => d ? (100 * n / d).toFixed(1) + "%" : "—";
  const activeStates = new Set(["warming", "running"]);
  let ready = false, busy = false, runId = null, latest = null, polling = false;
  const storageKey = "sr-compare-batch-run-v1";
  const saveId = value => { try { if (value) sessionStorage.setItem(storageKey, value); else sessionStorage.removeItem(storageKey); } catch (_) {} };
  const budget = () => {
    const rounds = Number(el("batch-rounds").value);
    text("batch-budget", `暖機 32 筆＋正式 ${rounds * 200} 筆＝最多 ${rounds * 200 + 32} 筆 SR-only 請求；並行數 C=1。`);
    if (!latest) { el("batch-progress").max = rounds * 200 + 32; text("batch-pairs", `0 / ${rounds * 100}`); text("batch-missing", `失敗／不完整：0 · 未嘗試：${rounds * 100}`); }
  };
  function controls() {
    el("batch-start").disabled = !ready || busy || !el("batch-ack").checked;
    el("batch-stop").disabled = !busy || !runId;
    el("batch-rounds").disabled = busy; el("batch-ack").disabled = busy;
    el("show-single").disabled = busy;
    el("batch-json").disabled = !latest; el("batch-csv").disabled = !latest;
  }
  function mode(batch) {
    if (busy || el("start").disabled) return;
    el("batch-view").hidden = !batch; el("single-view").hidden = batch;
    el("show-batch").setAttribute("aria-pressed", String(batch));
    el("show-single").setAttribute("aria-pressed", String(!batch));
  }
  el("show-batch").addEventListener("click", () => mode(true));
  el("show-single").addEventListener("click", () => mode(false));
  el("batch-ack").addEventListener("change", controls);
  el("batch-rounds").addEventListener("change", budget);
  function table(id, rows) {
    const tbody = el(id); tbody.replaceChildren();
    for (const cells of rows) {
      const tr = document.createElement("tr");
      for (const value of cells) { const td = document.createElement("td"); td.textContent = value; tr.appendChild(td); }
      tbody.appendChild(tr);
    }
  }
  function clearResult() {
    latest = null;
    for (const id of ["batch-ratio", "batch-agreement", "batch-bar-on-text", "batch-bar-off-text"]) text(id, "—");
    for (const id of ["batch-current", "batch-counts", "batch-paired-distribution", "batch-model-agreement"]) text(id, "");
    for (const id of ["batch-stat-rows", "batch-round-rows", "batch-recent"]) table(id, []);
    for (const mode of ["on", "off"]) el("batch-bar-" + mode).style.width = "0%";
    el("batch-progress").value = 0;
    text("batch-run-id", "正在建立新 run，尚無結果。");
    text("batch-result-warning", "尚未取得本次資料；不沿用上一批次數值。");
    budget();
  }
  function render(data) {
    latest = data; busy = activeStates.has(data.state); runId = data.run_id;
    const s = data.summary, planned = data.protocol.formal_requests + data.protocol.warmup_requests;
    el("batch-progress").max = planned; el("batch-progress").value = data.rows.length;
    const names = {warming:"暖機中",running:"正式計量中",completed:"全部完成",completed_with_errors:"完成，但有失敗記錄",cancelled:"已停止，保留部分結果",failed:"失敗停止，保留部分結果"};
    text("batch-status", `${names[data.state] || data.state} · ${data.rows.length} / ${planned} 筆 · 已經過 ${data.wall_seconds.toFixed(1)} 秒${data.reason ? " · " + data.reason : ""}`);
    text("batch-current", data.current ? `${data.current.phase === "warmup" ? "暖機" : "第 " + data.current.round + " 輪"} · ${data.current.prompt_id} · AMX ${data.current.mode.toUpperCase()}` : "目前無執行中的請求；缺少／失敗記錄不會自動補跑。");
    text("batch-run-id", `Run ID: ${runId} · 開始 UTC: ${data.created_utc} · Corpus SHA-256: ${data.protocol.corpus_sha256}`);
    text("batch-ratio", ratio(s.ratios.complexity_seconds.ratio_of_means_off_on));
    text("batch-pairs", `${s.successful_pairs} / ${s.planned_pairs}`);
    text("batch-missing", `失敗／不完整：${s.incomplete_or_failed_pairs} · 未嘗試：${s.unattempted_pairs}`);
    text("batch-agreement", percent(s.agreement.complexity, s.agreement_denominator));
    text("batch-model-agreement", `決策一致 ${percent(s.agreement.decision,s.agreement_denominator)} · 推薦模型一致 ${percent(s.agreement.models,s.agreement_denominator)} · 分母 ${s.agreement_denominator} 對`);
    const rows = [];
    for (const metric of ["complexity_seconds", "http_seconds"]) for (const m of ["on", "off"]) {
      const v = s.modes[m][metric];
      rows.push([`${metric === "complexity_seconds" ? "Complexity" : "SR-only HTTP"} / ${m.toUpperCase()}`, v.n, secs(v.mean), secs(v.p50), secs(v.p95), secs(v.min) + " – " + secs(v.max)]);
    }
    table("batch-stat-rows", rows);
    const max = Math.max(s.modes.on.complexity_seconds.mean || 0, s.modes.off.complexity_seconds.mean || 0);
    for (const m of ["on","off"]) { const mean = s.modes[m].complexity_seconds.mean; el("batch-bar-"+m).style.width = max && number(mean) ? (100*mean/max)+"%" : "0%"; text("batch-bar-"+m+"-text", secs(mean)); }
    text("batch-counts", `暖機 ${s.warmup_attempts}/32（失敗 ${s.warmup_failures}）；正式 ON：成功 ${s.modes.on.success}／失敗 ${s.modes.on.failed}／未嘗試 ${s.modes.on.unattempted}；OFF：成功 ${s.modes.off.success}／失敗 ${s.modes.off.failed}／未嘗試 ${s.modes.off.unattempted}。`);
    const paired = s.ratios.complexity_seconds.paired_off_on;
    text("batch-paired-distribution", `逐題配對比值 OFF/ON：P50 ${ratio(paired.p50)} · P95 ${ratio(paired.p95)} · 範圍 ${ratio(paired.min)} – ${ratio(paired.max)}（n=${paired.n}；不是信賴區間）。SR-only HTTP 配對均值比：${ratio(s.ratios.http_seconds.ratio_of_means_off_on)}。`);
    table("batch-round-rows", s.by_round.map(r => [r.round, `${r.successful_pairs} / 100`, ratio(r.complexity_ratio_off_on)]));
    table("batch-recent", data.rows.slice(-12).reverse().map(r => [r.phase === "warmup" ? "暖機" : "正式 / " + r.round, r.prompt_id, r.mode.toUpperCase(), r.outcome === "ok" ? "成功" : r.error, secs(r.complexity_seconds), secs(r.http_seconds), r.decision || "—"]));
    const mismatch = s.agreement_denominator && Object.values(s.agreement).some(n => n !== s.agreement_denominator);
    text("batch-result-warning", (busy ? "目前為進行中結果。" : data.state !== "completed" ? "此批次不是全成功完整結果，請查看失敗／未完成記錄。" : "完整批次已結束。") + (mismatch ? " ⚠ 有分類／決策／推薦模型不一致，已保留而非排除。" : "") + " 比值是目前配對樣本的描述性結果，不是獨立驗證的 AMX 因果倍率。");
    controls();
  }
  async function request(url, opts = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
    try { return await fetch(url, {...opts, cache:"no-store", signal:controller.signal}); }
    finally { clearTimeout(timeout); }
  }
  async function poll() {
    if (polling || !runId) return; polling = true;
    try {
      const response = await request("/api/compare/batch/" + runId);
      if (response.status === 404) {
        busy = false; saveId(null); controls();
        text("batch-status", "此 run 不存在、已過期或 Portal 已重啟。不會自動重跑；已有部分資料仍可下載。");
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);
      render(await response.json());
    } catch (_) {
      text("batch-status", "暫時無法讀取狀態，沒有重送測試。會繼續嘗試讀取；心跳中斷超過 45 秒會停止排程。已有資料可下載。");
    } finally { polling = false; }
    if (busy) setTimeout(poll, 1000);
  }
  el("batch-start").addEventListener("click", async () => {
    if (busy || !ready || !el("batch-ack").checked || el("start").disabled) return;
    const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
    runId = Array.from(bytes, b => b.toString(16).padStart(2,"0")).join("");
    clearResult(); busy = true; saveId(runId); controls();
    text("batch-status", "正在提交一次批次請求…");
    try {
      const response = await request("/api/compare/batch/start", {method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({run_id:runId,rounds:Number(el("batch-rounds").value),acknowledge_load:true})});
      const data = await response.json();
      if (!response.ok) { busy = false; saveId(null); controls(); text("batch-status", data.error || "未啟動"); return; }
    } catch (_) {
      text("batch-status", "提交回應不明；只查詢同一 run，不會再次提交或自動重跑。");
    }
    void poll();
  });
  el("batch-stop").addEventListener("click", async () => {
    if (!runId) return;
    el("batch-stop").disabled = true;
    try {
      const r = await request(`/api/compare/batch/${runId}/cancel`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
      if (!r.ok) throw new Error();
      text("batch-status", "已要求停止，等待目前一筆結束；保留所有已完成與失敗記錄。");
    } catch (_) { text("batch-status", "停止請求未確認；請重試停止，或關閉頁面讓 45 秒心跳保護停止排程。"); }
    controls();
  });
  const csvCell = value => {
    let s = value == null ? "" : Array.isArray(value) ? value.join(" | ") : String(value);
    if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g,'""') + '"';
  };
  function download(kind) {
    if (!latest) return;
    const fields = ["sequence","phase","round","pair_index","pair_position","prompt_id","prompt_sha256","language","intended_tier","length_band","mode","outcome","error","http_status","complexity_seconds","http_seconds","decision","models","complexity","received_utc"];
    const content = kind === "json" ? JSON.stringify(latest,null,2) : '\ufeff' + [fields.map(csvCell).join(","),...latest.rows.map(r=>fields.map(f=>csvCell(r[f])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([content],{type:kind === "json" ? "application/json" : "text/csv;charset=utf-8"}));
    const a = document.createElement("a"); a.href=url; a.download=`sr-only-${latest.run_id}.${kind}`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  el("batch-json").addEventListener("click",()=>download("json")); el("batch-csv").addEventListener("click",()=>download("csv"));
  async function init() {
    budget();
    try {
      const r = await request("/api/compare/batch/info"); const info = await r.json();
      if (!r.ok || !info.available || info.count !== 100 || info.warmups !== 16) throw new Error();
      ready = true;
      text("batch-corpus", `✓ 題庫已驗證：100 題＋16 題獨立暖機 · SHA-256: ${info.corpus_sha256}`);
    } catch (_) { text("batch-corpus", "題庫無法驗證，開始按鈕維持停用。沒有發送任何评估請求。"); }
    controls();
    try { runId = sessionStorage.getItem(storageKey); } catch (_) {}
    if (runId && /^[0-9a-f]{32}$/.test(runId)) { busy=true; controls(); void poll(); }
    else runId = null;
  }
  void init();
})();