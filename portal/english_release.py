"""English comparison UI only; never translate prompts, model output or metrics."""
import json
from pathlib import Path
import re

import parallel_release as previous

ROOT = Path(__file__).resolve().parent
portal = previous.portal
CATALOG = json.loads((ROOT / 'translations.json').read_text())
PATTERN = re.compile('|'.join(re.escape(k) for k in sorted(CATALOG, key=len, reverse=True)))


def translate(text):
    # Single pass: English replacements cannot be translated again.
    return PATTERN.sub(lambda m: CATALOG[m.group()], text)


def page_html():
    html = translate(previous.page_html())
    html = html.replace('lang="zh-Hant"', 'lang="en"').replace('lang="zh-TW"', 'lang="en"')
    return html


def pages():
    return {'/compare/': (page_html(), 'text/html'),
            '/compare/demo.js': (translate((ROOT / 'demo.js').read_text()), 'text/javascript'),
            '/compare/batch.js': (translate(previous.controller_js()), 'text/javascript'),
            '/compare/race.js': (translate(previous.chart_js()), 'text/javascript')}


class EnglishHandler(previous.ParallelHandler):
    def do_GET(self):
        if self.path in ('/compare/', '/compare/demo.js', '/compare/batch.js', '/compare/race.js') and self.requestline.split()[1] == self.path:
            text, mime = pages()[self.path]
            raw = text.encode()
            self.send_response(200)
            for key, value in {'Content-Type': mime + '; charset=utf-8', 'Content-Length': str(len(raw)),
                               'Content-Language': 'en', 'Cache-Control': 'no-store',
                               'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin',
                               'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()

    def _send_amx_json(self, code, data):
        # Translate only error messages, not arbitrary response payloads or results.
        if self.path.startswith('/api/compare/') and isinstance(data, dict) and isinstance(data.get('error'), str):
            data = {**data, 'error': translate(data['error'])}
        return super()._send_amx_json(code, data)

    def _emit(self, frame):
        if self.path == '/api/compare/stream':
            message = '此側上游請求失敗或逾時；沒有自動重送。請使用 Trace ID 排查。'
            if frame == portal.sse('error', {'message': message}):
                frame = portal.sse('error', {'message': CATALOG[message]})
        return super()._emit(frame)


portal.Handler = EnglishHandler

if __name__ == '__main__':
    portal.main()