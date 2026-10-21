"""Presentation-only stable time axis and solid comparison curves."""
from pathlib import Path
import white_release as white

race = white.race
portal = white.portal
previous_page = race.page_html


def page_html():
    css = '<style id="race-solid-lines">.race-stage .race-chart .series.on{stroke-dasharray:none}.race-stage .race-line.on{border-top-style:solid}</style>\n'
    return race.replace_once(previous_page(), '<section id="race-stage"', css + '<section id="race-stage"')


def chart_js():
    js = (Path(__file__).parent / "race.js").read_text()
    js = race.replace_once(js, 'let count=0, execution="parallel", run=null, lastState=null, lastReceived=0;',
                          'let count=0, execution="parallel", run=null, lastState=null, lastReceived=0;\n  let axisEnd=30;')
    js = race.replace_once(js, 'count=n; execution=selected; run=null; lastState=null; lastReceived=0;',
                          'count=n; execution=selected; run=null; lastState=null; lastReceived=0; axisEnd=30;')
    js = race.replace_once(js,
        'const end=Math.max(1,elapsed,...modes.flatMap(m=>rows[m].filter(r=>valid(r.completed_seconds)).map(r=>r.completed_seconds)));',
        '''const observed=Math.max(0,elapsed,...modes.flatMap(m=>rows[m].filter(r=>valid(r.completed_seconds)).map(r=>r.completed_seconds)));
    // Fixed 30-second blocks: no per-poll rescaling, no shrink at completion.
    if(observed>axisEnd)axisEnd=Math.ceil(observed/30)*30;
    const end=axisEnd;
    $("race-chart").dataset.axisEnd=String(end);''')
    return js


class ChartHandler(race.VisualHandler):
    def do_GET(self):
        if self.path == "/compare/race.js" and self.requestline.split()[1] == self.path:
            raw = chart_js().encode()
            self.send_response(200)
            for key, value in {"Content-Type": "text/javascript; charset=utf-8", "Content-Length": str(len(raw)),
                               "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()


race.page_html = page_html
portal.Handler = ChartHandler

if __name__ == "__main__":
    portal.main()