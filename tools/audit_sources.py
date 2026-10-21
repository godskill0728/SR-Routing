"""Metadata-only heuristic scan. Not a substitute for independent secret scanning."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "aws-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential-url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    "bearer-literal": re.compile(r"(?i)Bearer\s+[a-z0-9_.~-]{24,}"),
    "provider-key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
}
SENSITIVE = re.compile(r"(?i)^(?:api[_-]?key|password|passwd|master_key|client_secret|access_token|private_key)$")

def files():
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and not any(
        x in (".git", "__pycache__", ".venv", ".generated") for x in p.relative_to(ROOT).parts))

def scan():
    findings = []
    for path in files():
        rel = str(path.relative_to(ROOT))
        if path.is_symlink():
            findings.append({"path": rel, "line": 0, "rule": "symlink"})
            continue
        if path.suffix in (".so", ".bin", ".pem", ".key", ".safetensors", ".onnx", ".pyc") or path.name == ".env":
            findings.append({"path": rel, "line": 0, "rule": "excluded-file"})
        try:
            text = path.read_text()
        except UnicodeError:
            findings.append({"path": rel, "line": 0, "rule": "binary"})
            continue
        for line, content in enumerate(text.splitlines(), 1):
            for rule, pattern in PATTERNS.items():
                if pattern.search(content):
                    findings.append({"path": rel, "line": line, "rule": rule})
            match = re.match(r"\s*([\w-]+)\s*:\s*['\"]?([^#\n]+)", content)
            if match and SENSITIVE.fullmatch(match[1]) and not match[2].startswith("os.environ/"):
                findings.append({"path": rel, "line": line, "rule": "credential-config-value"})
        if path.suffix == ".py":
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and SENSITIVE.fullmatch(target.id) and node.value.value:
                            findings.append({"path": rel, "line": node.lineno, "rule": "credential-assignment"})
    return findings

if __name__ == "__main__":
    findings = scan()
    print(json.dumps({"files_scanned": len(files()), "findings": findings}, indent=2))
    raise SystemExit(bool(findings))