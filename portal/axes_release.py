"""Transpose success/time axes without changing measurement or scheduling."""
import cards_release as previous

portal = previous.portal
original_pages = previous.pages
replace = previous.replace


def pages():
    result = original_pages()
    html, mime = result['/compare/']
    html = replace(html, 'Cumulative successes / elapsed time', 'Elapsed time / cumulative successes')
    html = replace(html, '<text x="284" y="314" text-anchor="middle">Elapsed measured time (seconds)</text>',
        '<text x="284" y="314" text-anchor="middle">Successful requests</text>')
    html = replace(html, '<text x="15" y="154" text-anchor="middle" transform="rotate(-90 15 154)">Successful requests</text>',
        '<text x="15" y="154" text-anchor="middle" transform="rotate(-90 15 154)">Elapsed measured time (seconds)</text>')
    html = replace(html, '<h3>Elapsed time / cumulative successes</h3>',
        '<h3>Elapsed time / cumulative successes</h3><p class="hint">X: cumulative successful requests · Y: elapsed seconds. At the same success count, a lower curve means less time.</p>')
    result['/compare/'] = html, mime
    js, mime = result['/compare/race.js']
    js = replace(js, 'const x=t=>52+Math.min(end,t)/end*464,y=n=>273-n/count*240;',
        'const x=n=>52+Math.min(count,n)/count*464,y=t=>273-Math.min(end,t)/end*240;')
    js = replace(js, 'const yy=y(count*i/4),xx=x(end*i/4);', 'const yy=y(end*i/4),xx=x(count*i/4);')
    js = replace(js, 'String(count*i/4)', '(end*i/4).toFixed(1)')
    js = replace(js, '"text-anchor":"middle"},(end*i/4).toFixed(1)', '"text-anchor":"middle"},String(count*i/4)')
    js = replace(js, 'd+=` H ${x(r.completed_seconds)} V ${y(++n)}`;', 'd+=` V ${y(r.completed_seconds)} H ${x(++n)}`;')
    js = replace(js, 'd+=` H ${x(Math.max(until,0))}`;', 'd+=` V ${y(Math.max(until,0))}`;')
    js = replace(js, '$("race-chart").dataset.axisEnd=String(end);',
        '$("race-chart").dataset.axisEnd=String(end);\n    $("race-chart").dataset.xAxis="successes";\n    $("race-chart").dataset.yAxis="elapsed-seconds";')
    result['/compare/race.js'] = js, mime
    return result


previous.previous.english.pages = pages

if __name__ == '__main__':
    portal.main()