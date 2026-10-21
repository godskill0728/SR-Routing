"""Add bounded C=15 support and an explicit per-side concurrency selector."""
import english_release as english

parallel = english.previous
portal = english.portal
parallel.CONCURRENCIES = (1, 2, 4, 8, 15)
original_pages = english.pages
replace = parallel.race.replace_once


def pages():
    result = original_pages()
    html, mime = result['/compare/']
    html = replace(html, '<span>Shared start · C=1 per side</span>',
        '<label for="race-concurrency">Concurrency per side</label><select id="race-concurrency">'
        '<option value="1">1</option><option value="2">2</option><option value="4">4</option>'
        '<option value="8">8</option><option value="15" selected>15</option></select>')
    html = replace(html, 'Each side uses C=1.', 'Default C=15 per side; at most 30 measured requests in flight in total. Warmups remain serial.')
    result['/compare/'] = html, mime
    js, mime = result['/compare/batch.js']
    js = replace(js, 'const execution = el("race-execution").value;',
        'const execution = el("race-execution").value;\n    const concurrency = Number(el("race-concurrency").value);')
    js = replace(js, '"Independent queues, C=1 per side; at most 2 requests in flight in total."',
        '`Independent queues, C=${concurrency} per side; at most ${2*concurrency} measured requests in flight in total. Warmups remain serial.`')
    js = replace(js, 'el("race-execution").disabled = busy;', 'el("race-concurrency").disabled = busy; el("race-execution").disabled = busy;')
    js = replace(js, 'el("race-execution").addEventListener("change", budget);',
        'el("race-execution").addEventListener("change", budget);\n  el("race-concurrency").addEventListener("change", budget);')
    js = replace(js, 'el("race-execution").value = data.execution || "alternating"; budget();',
        'el("race-execution").value = data.execution || "alternating"; el("race-concurrency").value = String(data.concurrency_per_mode || 1); budget();')
    js = replace(js, 'execution:"parallel",acknowledge_load:true',
        'execution:"parallel",concurrency:Number(el("race-concurrency").value),acknowledge_load:true')
    result['/compare/batch.js'] = js, mime
    js, mime = result['/compare/race.js']
    js = replace(js, '"Independent queues · Total C≤2"',
        '`Independent queues · C per side=${document.getElementById("race-concurrency").value} · Total C≤${2*Number(document.getElementById("race-concurrency").value)}`')
    result['/compare/race.js'] = js, mime
    return result


class C15Handler(english.EnglishHandler):
    def _send_amx_json(self, code, data):
        if self.path == '/api/compare/visual/info' and code == 200:
            data = {**data, 'default_concurrency_per_mode': 15, 'concurrency_options': list(parallel.CONCURRENCIES)}
        if self.path == '/api/compare/visual/start' and code == 400 and 'error' in data:
            data = {**data, 'error': 'Only parallel, 1–5 rounds, and C=1/2/4/8/15 per side are supported; load acknowledgement is required.'}
        return super()._send_amx_json(code, data)


english.pages = pages
portal.Handler = C15Handler

if __name__ == '__main__':
    portal.main()