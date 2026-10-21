"""One fullscreen subtree for controls, progress, summary cards and live race."""
import profiles_release as previous

portal = previous.portal
original_pages = previous.pages
replace = previous.replace

CSS = '''<style id="demo-fullscreen-style">
#batch-demo:fullscreen {
  box-sizing:border-box;width:100%;height:100%;overflow:auto;
  padding:18px 24px;background:#f3f6fb;color:#172b43;color-scheme:light;
  display:flex;flex-direction:column;gap:12px;
}
#batch-demo:fullscreen>.composer {order:0;margin:0;padding:16px 20px;flex-shrink:0}
#batch-demo:fullscreen>.batch-cards {order:1;margin:0;flex-shrink:0}
#batch-demo:fullscreen>.race-stage {order:2;margin:0;padding:18px;flex-shrink:0}
#batch-demo:fullscreen>.composer>.batch-head,
#batch-demo:fullscreen>.composer>p.muted,
#batch-demo:fullscreen>.composer>.batch-flow,
#batch-demo:fullscreen #batch-corpus,
#batch-demo:fullscreen>.composer>p.batch-small:not([id]) {display:none}
#batch-demo:fullscreen .ack {margin:0 0 12px;padding:10px}
#batch-demo:fullscreen .batch-progress {margin-top:12px}
#batch-demo:fullscreen .batch-cards>div {padding:12px 18px}
#batch-demo:fullscreen .batch-number {font-size:28px}
#batch-demo:fullscreen .race-top {margin-bottom:12px}
#batch-demo:fullscreen .race-side {padding:12px}
#batch-demo:fullscreen .race-count {margin-top:6px}
#batch-demo:fullscreen #race-off-grid,
#batch-demo:fullscreen #race-on-grid {max-height:40vh;overflow:auto;scrollbar-gutter:stable}
#batch-demo:fullscreen .race-actions {position:sticky;top:0;z-index:2}
@media(max-width:760px){
  #batch-demo:fullscreen {padding:10px;gap:10px}
  #batch-demo:fullscreen>.composer {padding:12px}
}
</style>'''


def pages():
    result = original_pages()
    html, mime = result['/compare/']
    html = replace(html, '<section id="batch-view">', CSS+'\n<section id="batch-view">\n<div id="batch-demo">')
    marker = '<div class="batch-section"><h3>'
    assert html.count(marker) == 2
    # Close after the original summary cards, before detailed statistics.
    html = html.replace(marker, '</div>\n'+marker, 1)
    result['/compare/'] = html, mime
    js, mime = result['/compare/race.js']
    js = replace(js, 'await $("race-stage").requestFullscreen();', 'await $("batch-demo").requestFullscreen();')
    js = replace(js, 'window.RaceVisual={reset,render};', '''document.addEventListener("fullscreenchange",()=>{
    const active=document.fullscreenElement===$("batch-demo");
    $("race-fullscreen").textContent=active?"Exit fullscreen ⤡":"Fullscreen ⤢";
    $("race-fullscreen").setAttribute("aria-pressed",String(active));
  });
  window.RaceVisual={reset,render};''')
    result['/compare/race.js'] = js, mime
    return result


previous.previous.previous.previous.previous.english.pages = pages

if __name__ == '__main__':
    portal.main()