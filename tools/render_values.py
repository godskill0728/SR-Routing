"""Render portable Helm config values to stdout. No kubectl, network or secrets."""
import argparse
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parent.parent

def values(release):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", release):
        raise ValueError("invalid release name")
    configs = {"litellm": (ROOT / "routing/litellm.yaml").read_text()}
    for mode in ("on", "off"):
        config = yaml.safe_load((ROOT / "routing" / mode / "config.yaml").read_text())
        config["global"]["integrations"]["tools"]["enabled"] = False
        config["global"]["services"]["observability"]["tracing"]["enabled"] = False
        for model in config["providers"]["models"]:
            for backend in model["backend_refs"]:
                backend["endpoint"] = release + "-litellm:4000"
        configs[mode] = yaml.safe_dump(config, sort_keys=False)
        envoy = yaml.safe_load((ROOT / "routing" / mode / "envoy.yaml").read_text())
        envoy["admin"]["address"]["socket_address"]["address"] = "127.0.0.1"
        for cluster in envoy["static_resources"]["clusters"]:
            for endpoint in cluster["load_assignment"]["endpoints"]:
                for lb in endpoint["lb_endpoints"]:
                    socket = lb["endpoint"]["address"]["socket_address"]
                    socket["address"] = "127.0.0.1" if cluster["name"] == "extproc_service" else release + "-litellm"
        for listener in envoy["static_resources"]["listeners"]:
            for chain in listener["filter_chains"]:
                for filter_ in chain["filters"]:
                    for host in filter_["typed_config"]["route_config"]["virtual_hosts"]:
                        for route in host["routes"]:
                            route["route"]["host_rewrite_literal"] = release + "-litellm:4000"
        configs["envoy" + mode.title()] = yaml.safe_dump(envoy, sort_keys=False)
    return {"configs": configs}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default="sr-demo")
    print(yaml.safe_dump(values(parser.parse_args().release), sort_keys=False), end="")