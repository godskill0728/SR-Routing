"""Read-only native evidence sidecar. No credentials, inference, or arbitrary paths."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/evidence':
            self.send_error(404)
            return
        try:
            data = json.loads(Path('/evidence/sr-amx-evidence.json').read_text())
            assert data['mode'] in ('on', 'off')
            assert data['backend'] == 'openvino' and data['precision'] == 'bf16'
            assert type(data['amx_nodes']) is int and type(data['executed_nodes']) is int
            assert 0 <= data['amx_nodes'] <= data['executed_nodes'] and data['executed_nodes'] > 0
            body = json.dumps({k: data[k] for k in ('mode', 'backend', 'precision', 'amx_nodes', 'executed_nodes')}).encode()
        except (OSError, ValueError, KeyError, AssertionError):
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 9188), Handler).serve_forever()