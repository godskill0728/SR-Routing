"""Measured per-condition starting Y ranges; no fabricated data or clipping."""
import json
from pathlib import Path
import calibration_release as previous

portal=previous.portal
original_pages=previous.pages
replace=previous.previous.replace
PROFILE=json.loads((Path(__file__).parent/'axis_profiles.json').read_text())
LIMITS=PROFILE['y_max_seconds']
assert set(LIMITS)=={f'{n}:{c}' for n in range(100,501,100) for c in (1,4,8,15)}
assert all(type(v) is int and v>0 and v%4==0 for v in LIMITS.values())


def pages():
    result=original_pages()
    html,mime=result['/compare/']
    text='X: cumulative successful requests · Y: elapsed seconds. At the same success count, a lower curve means less time.'
    html=replace(html,text,text+' Starting Y ranges are calibrated per condition; ranges expand if exceeded. Compare values, not slopes across different settings.')
    html=replace(html,'<g id="race-chart-grid">','<g id="race-chart-grid">')
    html=replace(html,'<div class="race-legend">','<p id="race-axis-profile" class="hint" aria-live="polite"></p><div class="race-legend">')
    result['/compare/']=html,mime
    js,mime=result['/compare/race.js']
    js=replace(js,'let axisEnd=60;',
        'const axisProfiles='+json.dumps(LIMITS,sort_keys=True)+';\n  let axisEnd=60, axisBase=60, axisStep=30, axisConcurrency=1;')
    js=replace(js,'function reset(n, selected) {','function reset(n, selected, concurrency=Number($("race-concurrency").value)) {')
    js=replace(js,'lastReceived=0; axisEnd=60;',
        'lastReceived=0; axisConcurrency=concurrency;\n    axisBase=selected==="parallel"?(axisProfiles[`${n}:${concurrency}`]||60):60;\n    axisStep=axisBase/4; axisEnd=axisBase;')
    js=replace(js,'if(observed>axisEnd)axisEnd=Math.ceil(observed/30)*30;',
        'if(observed>axisEnd)axisEnd=Math.ceil(observed/axisStep)*axisStep;')
    js=replace(js,'$("race-chart").dataset.axisEnd=String(end);',
        '''$("race-chart").dataset.axisEnd=String(end);
    $("race-chart").dataset.axisBase=String(axisBase);
    const calibrated=execution==="parallel"&&Object.hasOwn(axisProfiles,`${count}:${axisConcurrency}`);
    set("race-axis-profile",`${count} per side · C=${axisConcurrency} · Y: 0–${end} s${end>axisBase?" (expanded)":""} · ${calibrated?"Measured Oct 19; ≥25% headroom":"Uncalibrated fallback"}`);''')
    js=replace(js,'const n=data.rounds*100,selected=data.execution||"alternating";',
        'const n=data.rounds*100,selected=data.execution||"alternating",concurrency=data.concurrency_per_mode||1;')
    js=replace(js,'if(run!==data.run_id||count!==n){reset(n,selected);run=data.run_id;}',
        'if(run!==data.run_id||count!==n||execution!==selected||axisConcurrency!==concurrency){reset(n,selected,concurrency);run=data.run_id;}')
    js=replace(js,'window.RaceVisual={reset,render};',
        '''for(const id of ["batch-rounds","race-concurrency"]){
    $(id).addEventListener("change",()=>{
      if(!["warming","running"].includes(lastState)) reset(Number($("batch-rounds").value)*100,"parallel");
    });
  }
  window.RaceVisual={reset,render};''')
    result['/compare/race.js']=js,mime
    return result


previous.previous.previous.previous.english.pages=pages

if __name__=='__main__':portal.main()