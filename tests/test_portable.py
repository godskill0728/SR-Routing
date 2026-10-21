"""Actual latest handler and rendered assets, loopback-only; no model requests."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "portal"))
sys.path.insert(0, str(ROOT / "tools"))
import fill_release as latest
import batch_release
from render_values import values

class PortableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = latest.portal.ThreadingHTTPServer(("127.0.0.1", 0), latest.portal.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d" % cls.server.server_port
        cls.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_latest_http_assets(self):
        for route in ("/", "/healthz", "/compare/", "/compare/demo.js", "/compare/batch.js", "/compare/race.js", "/reports/", "/reports/corpus/corpus.json"):
            with self.subTest(route=route), self.client.open(self.url+route, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_latest_ui_and_full_chain(self):
        pages = latest.pages()
        self.assertIn("Portable demo: synthetic corpus", pages["/compare/"][0])
        self.assertIn("demo-fill-style", pages["/compare/"][0])
        self.assertIn("--demo-extra-height", pages["/compare/race.js"][0])
        for module in ("fit_release", "fullscreen_release", "profiles_release", "axes_release", "binding_release", "parallel_release"):
            self.assertIn(module, sys.modules)

    def test_synthetic_corpus_pin(self):
        data = batch_release.corpus()
        self.assertEqual(len(data["prompts"]),100)
        self.assertEqual(len(data["warmups"]),16)
        self.assertIn("SYNTHETIC", data["description"])

    def test_missing_history_is_not_fabricated(self):
        routes = latest.portal.REPORT_ROUTES
        self.assertEqual(len(routes), 85)
        families = ("cpu-matrix", "numa-binding", "cpu-binding", "cpu-binding-c-sweep", "streams-comparison")
        self.assertEqual(len({routes["/reports/" + name + "/"][0] for name in families}), len(families))
        for route, (filename, _mime) in routes.items():
            self.assertNotRegex(route + filename, r"20\d{6}|(?:intel)?bnc\d+")
            if route in ("/reports/", "/reports/corpus/corpus.json"):
                continue
            self.assertFalse((ROOT / "reports-public" / filename).exists())
            with self.subTest(route=route), self.assertRaises(urllib.error.HTTPError) as error:
                self.client.open(self.url+route)
            self.assertEqual(error.exception.code,404)
        self.assertNotEqual(routes["/reports/numa-binding/v1.html"][0], routes["/reports/numa-binding/report-v2.html"][0])

    def test_controller_disabled(self):
        request=urllib.request.Request(self.url+"/api/amx",data=b'{}',headers={"Content-Type":"application/json"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.client.open(request)
        self.assertEqual(error.exception.code,403)

    def test_portable_config(self):
        import yaml
        for release in ("sr-demo", "fixture"):
            configs=values(release)["configs"]
            for mode in ("on","off"):
                raw = yaml.safe_load((ROOT / "routing" / mode / "config.yaml").read_text())
                raw_envoy = yaml.safe_load((ROOT / "routing" / mode / "envoy.yaml").read_text())
                for config, envoy, backend in (
                    (raw, raw_envoy, "sr-demo-litellm"),
                    (yaml.safe_load(configs[mode]), yaml.safe_load(configs["envoy"+mode.title()]), release+"-litellm"),
                ):
                    self.assertFalse(config["global"]["integrations"]["tools"]["enabled"])
                    tracing=config["global"]["services"]["observability"]["tracing"]
                    self.assertFalse(tracing["enabled"])
                    self.assertEqual(tracing["resource"]["service_name"], "sr-demo-"+mode)
                    self.assertEqual(tracing["exporter"]["endpoint"], "jaeger.example.invalid:4317")
                    models=config["providers"]["models"]
                    self.assertTrue(all(m["backend_refs"][0]["api_key_env"]=="LITELLM_API_KEY" for m in models))
                    self.assertTrue(all(m["backend_refs"][0]["endpoint"]==backend+":4000" for m in models))
                    self.assertEqual(envoy["admin"]["address"]["socket_address"]["address"], "127.0.0.1")
                    clusters={c["name"]: c for c in envoy["static_resources"]["clusters"]}
                    for name, cluster in clusters.items():
                        for endpoint in cluster["load_assignment"]["endpoints"]:
                            for lb in endpoint["lb_endpoints"]:
                                socket=lb["endpoint"]["address"]["socket_address"]
                                self.assertEqual(socket["address"], "127.0.0.1" if name=="extproc_service" else backend)
                    for listener in envoy["static_resources"]["listeners"]:
                        for chain in listener["filter_chains"]:
                            for filter_ in chain["filters"]:
                                for host in filter_["typed_config"]["route_config"]["virtual_hosts"]:
                                    routes=host["routes"]
                                    matches={r["match"]["headers"][0]["string_match"]["exact"]: r["route"]["cluster"] for r in routes if "headers" in r["match"]}
                                    self.assertEqual(matches, {"qwen3.5-4b-l4": "qwen3.5_4b_l4_cluster", "gemma-4-12b": "gemma_4_26b_cluster", "qwen3.8-27b": "qwen3.6_35b_cluster"})
                                    self.assertEqual(set(matches), {m["name"] for m in models})
                                    self.assertEqual(len(set(matches.values())), 3)
                                    self.assertTrue(set(matches.values()) <= set(clusters))
                                    self.assertTrue(all(r["route"]["host_rewrite_literal"]==backend+":4000" for r in routes))

if __name__ == "__main__": unittest.main()