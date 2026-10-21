"""Use spare fullscreen height for the actual chart and all request cells."""
import fit_release as previous

portal=previous.portal
# Keep historical report routes, but use an honest portable landing page.
portal.REPORT_ROUTES['/reports/'] = ('index.html', 'text/html; charset=utf-8')
original_pages=previous.pages
replace=previous.replace

CSS='''<style id="demo-fill-style">
#batch-demo:fullscreen .race-cells {
  grid-auto-rows:calc(9px + var(--demo-extra-height,0px) / var(--demo-cell-rows,25));
}
#batch-demo:fullscreen .race-cell {
  height:calc(9px + var(--demo-extra-height,0px) / var(--demo-cell-rows,25));
}
#batch-demo:fullscreen .race-chart {height:calc(255px + var(--demo-extra-height,0px))}
</style>'''


def pages():
    result=original_pages()
    html,mime=result['/compare/']
    html=replace(html,'<section id="batch-view">',CSS+'\n<section id="batch-view">')
    html=replace(html,'<section id="batch-view">',
      '<section id="batch-view"><p role="note" style="padding:10px;color:#674500;background:#fff5d6">'
      'Portable demo: synthetic corpus, not the deployed benchmark. Historical reports are not bundled; '
      'axis profiles are UI defaults, not a performance guarantee. '
      '<a href="/reports/">Details</a></p>')
    result['/compare/']=html,mime
    js,mime=result['/compare/race.js']
    js=replace(js,'surface.style.transform="none";',
        '''surface.style.transform="none";
    surface.style.setProperty("--demo-extra-height","0px");
    surface.style.setProperty("--demo-cell-rows",String(Math.max(1,Math.ceil(count/100)*5)));''')
    js=replace(js,'surface.style.left=Math.max(8,(root.clientWidth-surface.offsetWidth*scale)/2)+"px";',
        '''// Expand real content, not an empty container: both side grids and chart gain the spare height.
    const naturalHeight=Math.max(surface.offsetHeight,surface.scrollHeight);
    let extra=Math.max(0,availableHeight/scale-naturalHeight-2);
    surface.style.setProperty("--demo-extra-height",extra+"px");
    // Account for rounding/wrapped text without clipping anything.
    const overflow=Math.max(0,Math.max(surface.offsetHeight,surface.scrollHeight)-availableHeight/scale);
    if(overflow){extra=Math.max(0,extra-overflow-2);surface.style.setProperty("--demo-extra-height",extra+"px");}
    surface.style.left=Math.max(8,(root.clientWidth-surface.offsetWidth*scale)/2)+"px";''')
    result['/compare/race.js']=js,mime
    return result


previous.previous.previous.previous.previous.previous.previous.english.pages=pages

if __name__=='__main__':portal.main()