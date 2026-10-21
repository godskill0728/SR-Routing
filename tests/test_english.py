"""Offline translation scope, exact source preservation and HTTP regressions."""
import json
import os
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, os.environ['RACE_STAGE'])
import english_release as english
sys.path.insert(0, str(Path(__file__).parent.parent / 'amx-parallel-20261015'))
import test_parallel


class HTTPTest(test_parallel.HTTPTest):
    @classmethod
    def setUpClass(cls):
        cls.server = english.portal.ThreadingHTTPServer(('127.0.0.1', 0), english.EnglishHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def test_english_pages_no_cjk_and_static_content_not_changed(self):
        for url, (text, _) in english.pages().items():
            self.assertIsNone(re.search('[\u3400-\u9fff]', text), url)
            code, body = self.request(url)
            self.assertEqual(code, 200)
            self.assertEqual(body.decode(), text)
        self.assertIn('<html lang="en">', english.page_html())
        # No localization of form names, API routes, control values or request payloads.
        before = english.previous.page_html()
        after = english.page_html()
        for attribute in ('id', 'name', 'value', 'href', 'src'):
            pattern = attribute + r'="([^"]*)"'
            self.assertEqual(re.findall(pattern, before), re.findall(pattern, after))

    def test_api_errors_english_results_untouched(self):
        code, body = self.request('/api/compare/visual/start', {'bad': True})
        self.assertEqual(code, 400)
        self.assertIn('Requires parallel mode', json.loads(body)['error'])
        handler = english.EnglishHandler.__new__(english.EnglishHandler)
        handler.path = '/api/compare/batch/' + 'a'*32
        payload = {'decision': '成功', 'models': ['中文模型'], 'rows': [{'prompt_id': '題目一'}]}
        with patch.object(english.previous.ParallelHandler, '_send_amx_json') as send:
            handler._send_amx_json(200, payload)
            self.assertIs(send.call_args.args[1], payload)
            handler._send_amx_json(409, {'error': 'Portal 有其他比較進行中，未啟動新請求。'})
            self.assertIn('Another Portal comparison', send.call_args.args[1]['error'])

    def test_sse_translates_only_exact_static_error(self):
        handler = english.EnglishHandler.__new__(english.EnglishHandler)
        handler.path = '/api/compare/stream'
        error = '此側上游請求失敗或逾時；沒有自動重送。請使用 Trace ID 排查。'
        with patch.object(english.previous.ParallelHandler, '_emit') as emit:
            frame = english.portal.sse('content', {'text': '成功，這是中文回答。'})
            handler._emit(frame)
            emit.assert_called_with(frame)
            # Even text matching the static error must not be translated if it is model content.
            frame = english.portal.sse('content', {'text': error})
            handler._emit(frame)
            emit.assert_called_with(frame)
            handler._emit(english.portal.sse('error', {'message': error}))
            self.assertNotIn(error.encode(), emit.call_args.args[0])
            self.assertIn(b'upstream request failed', emit.call_args.args[0])
            handler.path = '/api/stream'
            frame = english.portal.sse('error', {'message': error})
            handler._emit(frame)
            emit.assert_called_with(frame)


if __name__ == '__main__':
    unittest.main()