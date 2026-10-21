import re
import unittest

import build


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.board, self.scrape, self.cm = build.resources()

    def test_distinct_additive_resources(self):
        self.assertNotEqual(self.board['uid'], 'sr-amx-benefit-v1')
        self.assertEqual(self.cm['metadata']['labels']['grafana_dashboard'], '1')
        self.assertEqual(self.scrape['metadata']['labels']['release'], 'example-prometheus')
        self.assertEqual(set(self.cm['data']), {'sr-router-operations-v1.json'})
        self.assertNotIn('grafana_folder', self.cm['metadata']['annotations'])

    def test_endpoint_mode_mapping(self):
        targets = self.scrape['spec']['staticConfigs']
        self.assertEqual([t['labels']['amx_mode'] for t in targets], ['on', 'off'])
        self.assertEqual(targets[0]['targets'], ['sr-demo-on:9190'])
        self.assertEqual(targets[1]['targets'], ['sr-demo-off:9190'])
        self.assertNotEqual(targets[0]['targets'], targets[1]['targets'])
        import json
        self.assertEqual(json.loads((build.HERE / 'scrapeconfig.json').read_text()), self.scrape)
        self.assertEqual(json.loads((build.HERE / 'dashboard.json').read_text()), self.board)

    def test_unique_ids_and_no_overlap(self):
        panels = self.board['panels']
        self.assertEqual(len(panels), len({p['id'] for p in panels}))
        for i, a in enumerate(panels):
            a = a['gridPos']
            self.assertLessEqual(a['x'] + a['w'], 24)
            for b in panels[i+1:]:
                b = b['gridPos']
                self.assertFalse(a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w']
                                 and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h'])

    def test_queries_scoped_without_zero_filling(self):
        for p in self.board['panels']:
            for t in p['targets']:
                self.assertNotIn('vector(0)', t['expr'])
                self.assertNotIn('clamp_min', t['expr'])
                self.assertEqual(t['datasource'], build.DS)
                self.assertTrue(build.SCOPE in t['expr'] or 'component="vllm-backend"' in t['expr'])

    def test_every_metric_is_collected(self):
        keep = re.compile(build.KEEP)
        for p in self.board['panels']:
            for t in p['targets']:
                for name in re.findall(r'([a-zA-Z_:][a-zA-Z0-9_:]*)\{', t['expr']):
                    self.assertTrue(name in ('up', 'scrape_duration_seconds') or keep.fullmatch(name), name)

    def test_bounded_allowlist(self):
        keep = re.compile(build.KEEP)
        for name in ('llm_model_requests_total', 'llm_request_errors_total',
                     'llm_signal_extraction_latency_seconds_bucket', 'process_resident_memory_bytes'):
            self.assertIsNotNone(keep.fullmatch(name))
        for name in ('llm_model_routerdc_similarity_bucket', 'go_memstats_alloc_bytes',
                     'arbitrary_request_prompt', 'llm_model_feedback_total'):
            self.assertIsNone(keep.fullmatch(name))

    def test_honest_boundaries(self):
        content = ' '.join(p.get('options', {}).get('content', '') for p in self.board['panels'])
        for caveat in ('not a controlled speedup', 'not a reliable success-rate', 'No historical', 'no live cache series'):
            self.assertIn(caveat, content)
        self.assertFalse(self.board['editable'])
        self.assertNotIn('secureJsonData', self.cm['data']['sr-router-operations-v1.json'])

    def test_rolling_and_cumulative_are_distinct(self):
        cumulative = next(p for p in self.board['panels'] if p['title'].startswith('Selected-model counters'))
        self.assertIn('NOT counts within', cumulative['description'])
        self.assertNotIn('increase(', cumulative['targets'][0]['expr'])
        self.assertEqual(self.board['templating']['list'][1]['refresh'], 1)


if __name__ == '__main__':
    unittest.main()