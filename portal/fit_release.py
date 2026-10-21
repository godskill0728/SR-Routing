"""Fit all demo controls and 500 cells per side inside the fullscreen viewport."""
import fullscreen_release as previous

portal=previous.portal
original_pages=previous.pages
replace=previous.replace

CSS='''<style id="demo-fit-style">
#demo-fit {display:contents}
#batch-demo:fullscreen {display:block;padding:0;overflow:hidden;position:relative}
#batch-demo:fullscreen>#demo-fit {
  position:absolute;left:8px;top:8px;display:flex;flex-direction:column;
  gap:8px;transform-origin:top left;box-sizing:border-box;
}
#batch-demo:fullscreen .race-layout {
  grid-template-columns:minmax(0,1fr) minmax(0,1.65fr) minmax(0,1fr);
  gap:12px;align-items:start;
}
#batch-demo:fullscreen .race-center {grid-column:auto;grid-row:auto;min-width:0}
#batch-demo:fullscreen .race-side {grid-column:auto;grid-row:auto;padding:10px}
#batch-demo:fullscreen #race-off-grid,
#batch-demo:fullscreen #race-on-grid {max-height:none;overflow:visible;scrollbar-gutter:auto}
#batch-demo:fullscreen .race-cells {
  grid-template-columns:repeat(20,minmax(0,1fr));grid-auto-rows:9px;gap:2px;
}
#batch-demo:fullscreen .race-cell {aspect-ratio:auto;height:9px;min-height:0;border-radius:1px}
#batch-demo:fullscreen .race-block-title {margin:5px 0 3px;font-size:9px}
#batch-demo:fullscreen .race-chart {height:255px;width:100%}
#batch-demo:fullscreen .race-count {font-size:26px;margin-top:2px}
#batch-demo:fullscreen .race-meter {margin:5px 0}
#batch-demo:fullscreen .race-clock {padding:9px}
#batch-demo:fullscreen .race-clock b {font-size:28px}
#batch-demo:fullscreen .race-top {margin-bottom:8px}
#batch-demo:fullscreen .race-stage h2 {font-size:20px}
#batch-demo:fullscreen .race-stage p {font-size:10px}
#batch-demo:fullscreen .race-note {padding:6px;font-size:10px}
#batch-demo:fullscreen .race-detail {padding:5px;font-size:10px}
#batch-demo:fullscreen .race-legend-boxes {margin:6px 0}
#batch-demo:fullscreen .ack {font-size:11px;margin:0 0 8px;padding:7px}
#batch-demo:fullscreen .batch-actions {flex-wrap:nowrap;gap:8px}
#batch-demo:fullscreen .batch-actions button {flex-basis:auto;padding:9px 12px}
#batch-demo:fullscreen .batch-actions select {flex:none}
#batch-demo:fullscreen .batch-actions label {font-size:12px}
#batch-demo:fullscreen .batch-progress {margin-top:6px;height:8px}
#batch-demo:fullscreen #batch-status {margin:6px 0;font-size:12px}
#batch-demo:fullscreen #batch-current,
#batch-demo:fullscreen #batch-budget {margin:4px 0;font-size:10px}
#batch-demo:fullscreen .batch-cards {grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
#batch-demo:fullscreen .batch-cards>div {padding:8px 12px}
#batch-demo:fullscreen .batch-number {font-size:24px}
#batch-demo:fullscreen .batch-cards .hint {font-size:10px}
</style>'''


def pages():
    result=original_pages()
    html,mime=result['/compare/']
    html=replace(html,'<div id="batch-demo">','<div id="batch-demo"><div id="demo-fit">')
    marker='</div>\n<div class="batch-section"><h3>'
    assert html.count(marker)==2
    html=html.replace(marker,'</div></div>\n<div class="batch-section"><h3>',1)
    html=html.replace('#batch-demo:fullscreen>', '#batch-demo:fullscreen>#demo-fit>')
    html=replace(html,'<section id="batch-view">',CSS+'\n<section id="batch-view">')
    result['/compare/']=html,mime
    js,mime=result['/compare/race.js']
    js=replace(js,'window.RaceVisual={reset,render};','''let fitFrame=0;
  function fitDemo(){
    fitFrame=0;
    const root=$("batch-demo"),surface=$("demo-fit");
    if(document.fullscreenElement!==root){surface.style.cssText="";return;}
    const availableWidth=Math.max(1,root.clientWidth-16),availableHeight=Math.max(1,root.clientHeight-16);
    surface.style.transform="none";
    let layoutWidth=Math.max(1024,availableWidth),scale=1;
    for(let i=0;i<6;i++){
      surface.style.width=layoutWidth+"px";
      const width=Math.max(surface.offsetWidth,surface.scrollWidth),height=Math.max(surface.offsetHeight,surface.scrollHeight);
      scale=Math.min(1,availableWidth/width,availableHeight/height);
      const next=Math.max(1024,Math.min(4096,availableWidth/scale));
      if(Math.abs(next-layoutWidth)<1||i===5)break;
      layoutWidth=next;
    }
    surface.style.left=Math.max(8,(root.clientWidth-surface.offsetWidth*scale)/2)+"px";
    surface.style.transform=`scale(${scale})`;
    surface.dataset.fitScale=String(scale);
  }
  function scheduleFit(){if(!fitFrame)fitFrame=requestAnimationFrame(fitDemo);}
  document.addEventListener("fullscreenchange",scheduleFit);
  window.addEventListener("resize",scheduleFit);
  new MutationObserver(()=>{if(document.fullscreenElement===$("batch-demo"))scheduleFit();})
    .observe($("demo-fit"),{subtree:true,childList:true,characterData:true});
  window.RaceVisual={reset,render};''')
    result['/compare/race.js']=js,mime
    return result


previous.previous.previous.previous.previous.previous.english.pages=pages

if __name__=='__main__':portal.main()