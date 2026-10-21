"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const set = (id, v) => { $(id).textContent = v; };
  const valid = n => typeof n === "number" && Number.isFinite(n) && n >= 0;
  const secs = n => valid(n) ? n.toFixed(3) + " s" : "—";
  const modes = ["off", "on"], cells = {off:[],on:[]};
  let count=0, execution="parallel", run=null, lastState=null, lastReceived=0;
  function reset(n, selected) {
    count=n; execution=selected; run=null; lastState=null; lastReceived=0;
    set("race-caption", `左右各 ${n} 格 · 正式合計 ${n*2} 筆 · 暖機 32 筆另計`);
    set("race-mode", execution === "parallel" ? "雙側獨立佇列 · 合計 C≤2" : "交替配對 · 全域 C=1");
    set("race-explanation", execution === "parallel" ? "共同起跑，每側一次一筆、各自前進，不逐題等待另一側。兩側可能競爭共享 CPU；曲線不是純 AMX 因果證明。" : "目前為交替排程，不是同時競跑。曲線包含等待另一側的時間；速度差異請搭配下方 Complexity／HTTP 配對統計解讀。");
    for (const mode of modes) {
      const root=$("race-"+mode+"-grid"); root.replaceChildren(); cells[mode]=[];
      for(let offset=0;offset<n;offset+=100){
        const title=document.createElement("div"); title.className="race-block-title";
        title.textContent=`第 ${offset/100+1} 輪 · ${offset+1}–${Math.min(n,offset+100)}`;root.appendChild(title);
        const grid=document.createElement("div");grid.className="race-cells";
        for(let i=offset;i<Math.min(n,offset+100);i++){
          const c=document.createElement("button");c.type="button";c.className="race-cell";c.dataset.state="pending";
          c.title=`AMX ${mode.toUpperCase()} · 第 ${i+1} 筆 · 未開始`;
          c.setAttribute("aria-label",c.title);
          for (const event of ["focus","mouseenter","click"]) c.addEventListener(event,()=>set("race-cell-detail",c.title));
          grid.appendChild(c);cells[mode].push(c);
        }
        root.appendChild(grid);
      }
      updateCount(mode,0);set("race-"+mode+"-state","待命");set("race-"+mode+"-stats","尚未開始");
      set("race-"+mode+"-time","—");set("race-"+mode+"-time-label","尚未起跑");
      $("race-"+mode+"-meter").style.width="0%";
    }
    set("race-outcome","待命；尚未產生測量結果。");
    set("race-cell-detail","指向、聚焦或點選格子，可看單筆狀態與耗時。未開始的格子不代表失敗。");
    set("race-freshness","依伺服器 monotonic 完成時間作圖；畫面約每 0.25 秒同步。");
    chart({off:[],on:[]},0,false);
  }
  function updateCount(mode,n){
    const node=$("race-"+mode+"-count");node.replaceChildren(document.createTextNode(String(n)+" "));
    const small=document.createElement("small");small.textContent=`/ ${count} 成功`;node.appendChild(small);
  }
  function chart(rows,elapsed,hasClock){
    const svgNS="http://www.w3.org/2000/svg",grid=$("race-chart-grid");grid.replaceChildren();
    const end=Math.max(1,elapsed,...modes.flatMap(m=>rows[m].filter(r=>valid(r.completed_seconds)).map(r=>r.completed_seconds)));
    const x=t=>52+Math.min(end,t)/end*464,y=n=>273-n/count*240;
    const add=(tag,attrs,label)=>{const e=document.createElementNS(svgNS,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(label!==undefined)e.textContent=label;grid.appendChild(e);};
    for(let i=0;i<=4;i++){
      const yy=y(count*i/4),xx=x(end*i/4);
      add("line",{x1:52,y1:yy,x2:516,y2:yy,class:"gridline"});add("text",{x:45,y:yy+4,"text-anchor":"end"},String(count*i/4));
      add("line",{x1:xx,y1:33,x2:xx,y2:273,class:"gridline"});add("text",{x:xx,y:292,"text-anchor":"middle"},(end*i/4).toFixed(1));
    }
    let total=0;
    for(const mode of modes){
      const sorted=rows[mode].filter(r=>valid(r.completed_seconds)).slice().sort((a,b)=>a.completed_seconds-b.completed_seconds);
      let n=0,d=`M ${x(0)} ${y(0)}`;
      for(const r of sorted){if(r.outcome!=="ok")continue;d+=` H ${x(r.completed_seconds)} V ${y(++n)}`;}
      // End each lane at its own last completion, or at the current shared time if still active.
      const finished=rows[mode].length===count;
      const until=finished&&sorted.length ? sorted[sorted.length-1].completed_seconds : elapsed;
      d+=` H ${x(Math.max(until,0))}`;
      $("race-"+mode+"-path").setAttribute("d",hasClock?d:"");total+=n;
    }
    $("race-chart-empty").style.display=hasClock?"none":"";
    $("race-chart").setAttribute("aria-label",hasClock?`累積成功曲線，實際 ${elapsed.toFixed(3)} 秒；兩側合計成功 ${total} 筆。` : "尚無可用的正式完成時間，不繪製模擬曲線");
  }
  function render(data){
    const n=data.rounds*100,selected=data.execution||"alternating";
    if(run!==data.run_id||count!==n){reset(n,selected);run=data.run_id;}
    lastReceived=performance.now();lastState=data.state;
    const active=["warming","running"].includes(data.state),elapsed=data.measured_elapsed_seconds;
    const rows={off:[],on:[]};
    for(const row of data.rows)if(row.phase==="measured"&&rows[row.mode])rows[row.mode].push(row);
    const success={},finish={};
    for(const mode of modes){
      const m=rows[mode],failed=m.filter(r=>r.outcome!=="ok").length;success[mode]=m.length-failed;
      const indexed=new Map(m.map(r=>[(r.round-1)*100+r.pair_index,r]));
      const current=data.current_by_mode?.[mode] || (data.current?.mode===mode?data.current:null);
      for(let i=0;i<count;i++){
        const row=indexed.get(i),c=cells[mode][i];
        let status=row?(row.outcome==="ok"?"ok":"error"):
          active&&current?.phase==="measured"&&(current.round-1)*100+current.pair_index===i?"running":"pending";
        c.dataset.state=status;
        const labels={ok:"成功",error:"失敗",running:"執行中",pending:active?"未開始":"未執行"};
        c.title=`AMX ${mode.toUpperCase()} · 第 ${i+1} 筆 · ${labels[status]}`+(row?` · ${row.prompt_id} · Complexity ${secs(row.complexity_seconds)} · HTTP ${secs(row.http_seconds)} · 完成於 ${secs(row.completed_seconds)}${row.error?" · "+row.error:""}`:"");
        c.setAttribute("aria-label",c.title);
      }
      updateCount(mode,success[mode]);$("race-"+mode+"-meter").style.width=(100*success[mode]/count)+"%";
      const inFlight=active&&current?.phase==="measured"?1:0;
      set("race-"+mode+"-stats",`成功 ${success[mode]} · 失敗 ${failed} · 在途 ${inFlight} · 未開始 ${count-m.length-inFlight}`);
      const all=m.length===count;
      set("race-"+mode+"-state",data.state==="warming"?"暖機中":all?(failed?"結束 · 有失敗":"全部成功"):active?"進行中":"已停止");
      finish[mode]=all&&m.every(r=>valid(r.completed_seconds))?Math.max(...m.map(r=>r.completed_seconds)):null;
      set("race-"+mode+"-time",secs(all?finish[mode]:elapsed));
      set("race-"+mode+"-time-label",all?(failed?"本側結束 · 不宣稱全成功":"本側最後一筆完成時間"):valid(elapsed)?(active?"共同起點至本次快照 · 尚未完成":"停止時已經過 · 非完成時間"):"暖機不納入正式計時");
    }
    chart(rows,valid(elapsed)?elapsed:0,valid(elapsed));
    let message;
    if(selected!=="parallel")message="交替排程：完成格呈現真實進度，但兩側被依序排程，不宣告競跑勝負。";
    else if(data.state==="completed"&&success.off===count&&success.on===count&&valid(finish.off)&&valid(finish.on)){
      const gap=Math.abs(finish.off-finish.on);
      message=gap<.001?"兩側在毫秒顯示精度內同時完成。":`本次 AMX ${finish.off<finish.on?"OFF":"ON"} 先完成，差 ${gap.toFixed(3)} 秒。這是本次共享資源下的完成差，不是純 AMX 加速倍率。`;
    }else if(!active)message="批次已停止或含失敗；保留灰／紅格，不補成成功，也不宣告完整競跑勝負。";
    else if(data.state==="warming")message=`暖機 ${data.rows.filter(r=>r.phase==="warmup").length} / 32；暖機完成後才啟動兩側正式計時。`;
    else message=`目前成功 OFF ${success.off} / ON ${success.on}；正式測量中，未預設哪一側較快。`;
    set("race-outcome",message);set("race-freshness",`已同步 ${data.rows.length} 筆（含暖機）；線條依真實完成秒數，不用輪詢到達時間。`);
  }
  setInterval(()=>{
    if(lastReceived&&["warming","running"].includes(lastState)&&performance.now()-lastReceived>3000)
      set("race-freshness","狀態超過 3 秒未更新；格子與計時保持最後快照，不推測完成。請檢查連線。");
  },1000);
  $("race-fullscreen").addEventListener("click",async()=>{
    try{if(document.fullscreenElement)await document.exitFullscreen();else await $("race-stage").requestFullscreen();}
    catch(_){set("race-freshness","此瀏覽器不支援全螢幕；仍可在一般頁面查看。");}
  });
  window.RaceVisual={reset,render};
})();