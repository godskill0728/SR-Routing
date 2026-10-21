#!/usr/bin/env python3
"""Build a separate, read-only SR operations dashboard and additive resources."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
UID = 'sr-router-operations-v1'
DS = {'type': 'prometheus', 'uid': 'example-prometheus'}
SCOPE = 'sr_dashboard="router-operations-v1"'
SR = SCOPE + ',amx_mode=~"$mode"'
MODEL = SR + ',model=~"$model",model!="_init"'
KEEP = ('llm_(model_requests_total|request_errors_total|decision_(evaluation_total|match_total)|'
        'signal_extraction_total|model_(prompt_tokens_total|completion_tokens_total)|'
        '(model_routing_latency|signal_extraction_latency|decision_evaluation_latency|'
        'model_completion_latency|model_ttft)_seconds_(bucket|sum|count))|'
        'process_(cpu_seconds_total|resident_memory_bytes|start_time_seconds)|go_goroutines')


def metric(name, labels=SR):
    return name + '{' + labels + '}'


def rate(name, labels=SR, group='amx_mode'):
    return f'sum by ({group}) (rate({metric(name, labels)}[$__rate_interval]))'


def mean(name, labels=SR, group='amx_mode'):
    return f'1000 * {rate(name + "_sum", labels, group)} / {rate(name + "_count", labels, group)}'


def quantile(name, q, labels=SR):
    return f'1000 * histogram_quantile({q}, sum by (le, amx_mode) (rate({metric(name + "_bucket", labels)}[$__rate_interval])))'


def dashboard():
    panels = []

    def panel(title, kind, x, y, w, h, queries=(), unit='short', description=''):
        p = {'id': len(panels) + 1, 'title': title, 'type': kind,
             'gridPos': dict(x=x, y=y, w=w, h=h), 'description': description,
             'datasource': DS, 'interval': '15s',
             'fieldConfig': {'defaults': {'unit': unit, 'decimals': 2, 'noValue': 'No samples',
                                          'color': {'mode': 'palette-classic'}}, 'overrides': []},
             'targets': [dict(refId=chr(65+i), expr=q, legendFormat=legend, datasource=DS,
                              editorMode='code', range=kind == 'timeseries', instant=kind != 'timeseries')
                         for i, (q, legend) in enumerate(queries)]}
        if kind == 'timeseries':
            p['options'] = {'legend': {'displayMode': 'table', 'placement': 'bottom', 'calcs': ['lastNotNull', 'max']},
                            'tooltip': {'mode': 'multi', 'sort': 'desc'}}
            p['fieldConfig']['defaults']['custom'] = {'drawStyle': 'line', 'lineWidth': 2, 'fillOpacity': 10,
                'spanNulls': False, 'showPoints': 'never', 'stacking': {'mode': 'none', 'group': 'A'}}
        elif kind in ('stat', 'bargauge'):
            p['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'values': False},
                            'orientation': 'horizontal', 'colorMode': 'value', 'graphMode': 'none',
                            'textMode': 'value_and_name', 'displayMode': 'gradient', 'showUnfilled': True}
        panels.append(p)
        return p

    def text(title, content, y, h=4):
        p = panel(title, 'text', 0, y, 24, h)
        p['options'] = {'mode': 'markdown', 'content': content}

    def row(title, y):
        panel(title, 'row', 0, y, 24, 1)['collapsed'] = False

    text('SEMANTIC ROUTER / OPERATIONS',
         '## Route intelligently. Observe each layer separately.\n'
         '**Client → SR (ON / OFF) → LiteLLM → vLLM** · Independent live monitoring · 15-second collection\n\n'
         'ON / OFF identifies the **service configuration**, not per-request AMX kernel execution. '
         'Different live traffic is **not a controlled speedup experiment**. Mode filters apply to all SR panels; '
         'Model filters apply only to model-labelled panels. Missing series are never replaced with zero.', 0, 5)
    health = panel('Router metrics / scrape health', 'stat', 0, 5, 6, 5,
                   [(metric('up'), 'AMX {{amx_mode}}')], description='1 = metrics reachable; not inference or backend health.')
    health['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
        '0': {'text': 'DOWN', 'color': 'red'}, '1': {'text': 'UP', 'color': 'green'}}}]
    panel('Selected-model requests / second', 'stat', 6, 5, 6, 5,
          [(rate('llm_model_requests_total', MODEL), 'AMX {{amx_mode}}')], 'reqps',
          'Instrumented request paths, not successful answers. A rejected request may not reach a selected model.')
    panel('Selected-model requests / time range', 'stat', 12, 5, 6, 5,
          [(f'sum by (amx_mode) (increase({metric("llm_model_requests_total", MODEL)}[$__range]))', 'AMX {{amx_mode}}')],
          description='Prometheus extrapolated increase; can be fractional. Only covers data since this collector began, not earlier requests.')
    panel('Routing P95 / rolling window', 'stat', 18, 5, 6, 5,
          [(quantile('llm_model_routing_latency_seconds', .95), 'AMX {{amx_mode}}')], 'ms',
          'Instrumented ext_proc routing only. Idle window = No samples, not zero latency. Histogram estimate; highest finite bucket 10 s.')

    row('01 / TRAFFIC & MODEL ROUTING', 10)
    panel('Model traffic / instrumented requests', 'timeseries', 0, 11, 12, 8,
          [(rate('llm_model_requests_total', MODEL, 'amx_mode, model'), '{{amx_mode}} · {{model}}')], 'reqps')
    panel('Model requests / selected time range', 'bargauge', 12, 11, 12, 8,
          [(f'sum by (amx_mode, model) (increase({metric("llm_model_requests_total", MODEL)}[$__range]))', '{{amx_mode}} · {{model}}')],
          description='Not successful response counts. No pre-collection history is reconstructed from cumulative counters.')
    panel('Selected-model counters / since router process start', 'bargauge', 0, 19, 12, 8,
          [(f'sum by (amx_mode, model) ({metric("llm_model_requests_total", MODEL)})', '{{amx_mode}} · {{model}}')],
          description='Cumulative process counters at the selected end time; NOT counts within the selected time range. Reset on restart.')
    panel('Decision matches / multiple matches allowed', 'timeseries', 12, 19, 12, 8,
          [(rate('llm_decision_match_total', SR, 'amx_mode, decision_name'), '{{amx_mode}} · {{decision_name}}')], 'ops',
          'All matched rules, including default-route. Several rules can match one request. Do not use as request count or exclusive route share.')

    row('02 / ROUTER LATENCY — NOT LLM GENERATION', 27)
    for x, y, name, title, labels in [
        (0, 28, 'llm_model_routing_latency_seconds', 'Routing / mean & P95', SR),
        (12, 28, 'llm_signal_extraction_latency_seconds', 'Complexity / mean & P95', SR + ',signal_type="complexity"')]:
        panel(title, 'timeseries', x, y, 12, 8,
              [(mean(name, labels), '{{amx_mode}} · mean'), (quantile(name, .95, labels), '{{amx_mode}} · P95')], 'ms',
              'Complexity includes embedding + rule scoring, excludes outer gate wait. Routing covers instrumented ext_proc paths, not every API/eval request. Idle = no latency sample.')
    panel('Routing / P50 · P95 · P99', 'timeseries', 0, 36, 12, 8,
          [(quantile('llm_model_routing_latency_seconds', q), '{{amx_mode}} · ' + label)
           for q, label in ((.5, 'P50'), (.95, 'P95'), (.99, 'P99'))], 'ms',
          'Bucket-interpolated estimates, not exact percentiles. Highest finite bucket is 10 s; overflow can cap estimates. Do not subtract percentiles.')
    panel('Decision evaluation / mean', 'timeseries', 12, 36, 12, 8,
          [(mean('llm_decision_evaluation_latency_seconds'), '{{amx_mode}} · mean')], 'ms',
          'Rule evaluation only. Distinct from complexity extraction and full routing; not a backend latency.')

    row('03 / SR-OBSERVED RESPONSES & ERRORS', 44)
    text('Measurement boundary / read before comparing',
         '**SR response duration ≠ LiteLLM / Langfuse LLM observation duration.** SR timers use router request context and can include routing, '
         'network, queueing and upstream handling; recorded responses may include error bodies. Streaming TTFT records the first body chunk '
         '(possibly role-only); non-streaming uses response headers. Neither is guaranteed to be the first visible text token.\n\n'
         '**Errors are recorded events, not a reliable success-rate denominator.** Unseen label combinations remain absent. '
         'Langfuse observation duration requires the actual LiteLLM trace; this dashboard does not invent trace, cost, or cache-hit data.', 45, 5)
    for x, name, title in [(0, 'llm_model_completion_latency_seconds', 'SR-observed response duration / mean'),
                           (12, 'llm_model_ttft_seconds', 'SR-observed first chunk / headers / mean')]:
        panel(title, 'timeseries', x, 50, 12, 8,
              [(mean(name, MODEL, 'amx_mode, model'), '{{amx_mode}} · {{model}}')], 'ms',
              'Not Langfuse generation time. Native SR instrumentation can record error responses; zero-traffic windows have no latency.')
    panel('Recorded error events / second', 'timeseries', 0, 58, 12, 8,
          [(rate('llm_request_errors_total', MODEL, 'amx_mode, model, reason'), '{{amx_mode}} · {{model}} · {{reason}}')], 'ops',
          'Native errors only, not complete HTTP status accounting. OFF may have no error series until its first error; missing is not proof of zero errors.')
    panel('Recorded error events / time range', 'bargauge', 12, 58, 12, 8,
          [(f'sum by (amx_mode, model, reason) (increase({metric("llm_request_errors_total", MODEL)}[$__range]))', '{{amx_mode}} · {{model}} · {{reason}}')],
          description='Extrapolated event increase. No series means unobserved, not certified zero. Errors can occur before model assignment.')
    panel('SR-recorded tokens / second', 'timeseries', 0, 66, 12, 8,
          [(rate('llm_model_prompt_tokens_total', MODEL, 'amx_mode, model'), '{{amx_mode}} · {{model}} · prompt'),
           (rate('llm_model_completion_tokens_total', MODEL, 'amx_mode, model'), '{{amx_mode}} · {{model}} · completion')], 'ops',
          'Token accounting observed by SR, dependent on upstream usage fields. Not authoritative LiteLLM billing or token-generation throughput.')
    panel('Response observations above 10 s / second', 'timeseries', 12, 66, 12, 8,
          [(rate('llm_model_completion_latency_seconds_count', MODEL, 'amx_mode, model') + ' - ' +
            rate('llm_model_completion_latency_seconds_bucket', MODEL + ',le="10"', 'amx_mode, model'), '{{amx_mode}} · {{model}}')], 'ops',
          'Observations beyond the highest finite native histogram bucket. Completion quantiles would saturate here; use means and actual traces instead.')

    row('04 / ROUTER PROCESS RESOURCES', 74)
    panel('Process CPU / cores consumed', 'timeseries', 0, 75, 12, 8,
          [(rate('process_cpu_seconds_total'), 'AMX {{amx_mode}}')], 'cores',
          'User + system CPU of router process, including native work. Not node CPU, container quota percent, or AMX utilization.')
    panel('Process resident memory / RSS', 'timeseries', 12, 75, 12, 8,
          [(metric('process_resident_memory_bytes'), 'AMX {{amx_mode}}')], 'bytes',
          'Router process RSS. Not total Pod memory or cgroup working set; excludes sidecars.')
    panel('Go goroutines', 'timeseries', 0, 83, 12, 7, [(metric('go_goroutines'), 'AMX {{amx_mode}}')],
          description='Go concurrency; not native threads, active requests, or CPU cores.')
    panel('Router process uptime', 'stat', 12, 83, 12, 7,
          [('time() - ' + metric('process_start_time_seconds'), 'AMX {{amx_mode}}')], 's')

    row('05 / COLLECTION COVERAGE', 90)
    panel('Legacy GPU metrics targets / NOT current route health', 'stat', 0, 91, 12, 6,
          [('up{sr_observability="amx",component="vllm-backend"}', '{{backend}} · {{instance}}')],
          description='Existing separate collector still used obsolete backend IPs at publication. Down scrape targets do not establish LiteLLM route health. Unchanged by this dashboard.')
    panel('Router scrape duration', 'timeseries', 12, 91, 12, 6,
          [(metric('scrape_duration_seconds'), 'AMX {{amx_mode}}')], 's')
    text('Coverage / interpretation',
         '- **New collection starts at deployment:** rate/increase needs at least two scrapes. No historical ON/OFF backfill. '
         'Cumulative counters can already contain requests from before collection.\n'
         '- **Idle latency is unknown, not zero:** use a wider time range only if traffic occurred after collection started. '
         'No inference or load test was generated to populate charts.\n'
         '- **Legacy GPU targets:** existing collector IPs are stale. This release does not change them or diagnose current model connectivity.\n'
         '- **Not collected here:** Langfuse observations, authoritative costs, gate wait, GPU queue time on current backends, '
         'cache hits (no live cache series observed), per-request AMX kernel execution.\n'
         '- **Isolation:** queries select a dedicated collection label to avoid double-counting the old ON-only job. '
         'Original SR management UI and AMX benchmark dashboard remain separate.', 97, 7)
    return {'id': None, 'uid': UID, 'title': 'Semantic Router | Operations · ON / OFF', 'schemaVersion': 41,
            'version': 1, 'editable': False, 'tags': ['semantic-router', 'operations', 'litellm', 'on-off'],
            'timezone': 'browser', 'refresh': '30s', 'time': {'from': 'now-1h', 'to': 'now'},
            'graphTooltip': 1, 'panels': panels, 'annotations': {'list': []},
            'links': [{'title': 'Original AMX benchmark dashboard', 'type': 'link', 'url': '/d/sr-amx-benefit-v1', 'targetBlank': True},
                      {'title': 'Official SR dashboard reference', 'type': 'link', 'url': 'https://github.com/vllm-project/semantic-router/tree/main/dashboard', 'targetBlank': True}],
            'templating': {'list': [
                {'name': 'mode', 'label': 'Service AMX mode', 'type': 'custom', 'query': 'on,off',
                 'multi': True, 'includeAll': True, 'allValue': '.*', 'current': {'text': 'All', 'value': '$__all'},
                 'options': [{'text': 'on', 'value': 'on', 'selected': False}, {'text': 'off', 'value': 'off', 'selected': False}]},
                {'name': 'model', 'label': 'Model (model panels only)', 'type': 'query', 'datasource': DS,
                 'query': {'query': 'label_values(' + metric('llm_model_requests_total') + ', model)', 'refId': 'ModelVariable'},
                 'refresh': 1, 'sort': 1, 'multi': True, 'includeAll': True, 'allValue': '.*',
                 'current': {'text': 'All', 'value': '$__all'}, 'options': []}]}}


def resources():
    board = dashboard()
    body = json.dumps(board, ensure_ascii=False, indent=2) + '\n'
    labels = {'app.kubernetes.io/part-of': 'sr-router-operations'}
    scrape = {'apiVersion': 'monitoring.coreos.com/v1alpha1', 'kind': 'ScrapeConfig',
              'metadata': {'name': 'sr-router-operations-v1', 'namespace': 'default',
                           'labels': dict(labels, release='example-prometheus')},
              'spec': {'metricsPath': '/metrics', 'scrapeInterval': '15s', 'scrapeTimeout': '8s',
                       'metricRelabelings': [{'action': 'keep', 'sourceLabels': ['__name__'], 'regex': KEEP}],
                       'staticConfigs': [
                           {'targets': ['sr-demo-on:9190'],
                            'labels': {'sr_dashboard': 'router-operations-v1', 'amx_mode': 'on', 'component': 'semantic-router'}},
                           {'targets': ['sr-demo-off:9190'],
                            'labels': {'sr_dashboard': 'router-operations-v1', 'amx_mode': 'off', 'component': 'semantic-router'}}]}}
    cm = {'apiVersion': 'v1', 'kind': 'ConfigMap',
          'metadata': {'name': 'sr-router-operations-dashboard-v1', 'namespace': 'default',
                       'labels': dict(labels, grafana_dashboard='1'),
                       'annotations': {'sr-dashboard-sha256': hashlib.sha256(body.encode()).hexdigest()}},
          'data': {'sr-router-operations-v1.json': body}}
    return board, scrape, cm


if __name__ == '__main__':
    for name, value in zip(('dashboard.json', 'scrapeconfig.json', 'configmap.json'), resources()):
        # Never silently overwrite earlier release artifacts.
        path = HERE / name
        content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        if path.exists():
            if path.read_text() != content:
                raise SystemExit('Existing artifact differs: ' + str(path))
        else:
            with path.open('x') as out:
                out.write(content)
        print(name, hashlib.sha256(content.encode()).hexdigest())