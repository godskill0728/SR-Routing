"""Offline validation: syntax, isolated regression suites, rendered JS, Helm and scan."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent

def run(args, **kwargs):
    result=subprocess.run(args,cwd=ROOT,**kwargs)
    if result.returncode: raise SystemExit(result.returncode)

def main():
    for path in ROOT.rglob("*.py"):
        if not any(x in (".git",".venv",".generated") for x in path.parts):
            compile(path.read_bytes(),str(path.relative_to(ROOT)),"exec")
    env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1",**{n:str(ROOT/"portal") for n in ("COMPARE_STAGE","BATCH_STAGE","RACE_STAGE")}}
    for name in ("compare","batch","race","parallel","english","c15","portable"):
        run([sys.executable,"-B","-m","unittest","discover","-s","tests","-p","test_"+name+".py"],env=env)
    run([sys.executable,"-B","-m","unittest","discover","-s","observability","-p","test_build.py"],env=env)
    sys.path.insert(0,str(ROOT/"portal"))
    import fill_release
    with tempfile.TemporaryDirectory(prefix="sr-js-") as temp:
        snippets=[]
        for path in (ROOT/"portal").glob("*.js"): snippets.append(path.read_text())
        for route,(body,mime) in fill_release.pages().items():
            if "javascript" in mime: snippets.append(body)
            elif "html" in mime: snippets.extend(re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>",body,re.S))
        snippets.extend(re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>",fill_release.portal.INDEX_HTML,re.S))
        for i,body in enumerate(snippets):
            file=Path(temp)/("asset-%d.js"%i);file.write_text(body)
            run(["node","--check",str(file)],capture_output=True)
        print("JavaScript syntax checked:",len(snippets),"raw/rendered scripts")
    run(["helm","lint","deploy/chart"])
    from render_values import values
    import yaml
    config=yaml.safe_dump(values("sr-demo"))
    args=["helm","template","sr-demo","deploy/chart","-f","-","--set","stack.enabled=true","--set","stack.routerImage=example.invalid/sr:reviewed","--set","stack.litellmImage=example.invalid/litellm:reviewed","--set","stack.modelPVC=sr-models"]
    result=subprocess.run(args,input=config,text=True,capture_output=True,cwd=ROOT)
    if result.returncode: raise SystemExit("Helm stack render failed")
    docs=list(yaml.safe_load_all(result.stdout))
    assert len(docs)==11 and all(d["kind"]!="Secret" for d in docs)
    print("Full Helm render: 11 objects, zero Secret objects")
    run([sys.executable,"-B","tools/audit_sources.py"])

if __name__ == "__main__": main()