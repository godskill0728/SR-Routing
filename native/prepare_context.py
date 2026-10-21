"""Copy a reviewed upstream checkout into an ignored build context, with base checks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent

def prepare(upstream):
    upstream = upstream.resolve(strict=True)
    pins = json.loads((HERE / "upstream-base-hashes.json").read_text())["base_files"]
    for name, expected in pins.items():
        if hashlib.sha256((upstream / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Upstream mismatch: " + name + "; review the base rather than bypassing checks")
    target = HERE / "semantic-router-0.3.0"
    if target.exists():
        raise ValueError("Build context exists; use a clean context after review")
    shutil.copytree(upstream, target, ignore=shutil.ignore_patterns(
        ".git", "node_modules", "target", "build", "__pycache__", ".env", "*.log"))
    shutil.copytree(HERE / "overlay", target, dirs_exist_ok=True)
    print("Verified base and copied source overlay. Native libraries must be built separately.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    prepare(parser.parse_args().upstream)