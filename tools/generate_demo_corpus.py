"""Generate synthetic, non-measured demo inputs; never copy production prompts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "reports-public"

def content():
    topics = ("binary search", "HTTP caching", "unit tests", "queues", "sorting",
              "database indexes", "Unicode", "recursion", "time zones", "checksums")
    tasks = ("Define {} in one sentence.", "Give a simple example of {}.",
             "Explain two common mistakes involving {}.", "Compare two approaches to {}.",
             "Outline a beginner lesson about {}.", "Describe how to test {}.",
             "List three limitations of {}.", "Give pseudocode demonstrating {}.",
             "Explain a performance tradeoff involving {}.", "Design a small exercise about {}.")
    return {"description": "SYNTHETIC DEMO ONLY. Not the deployed benchmark corpus; no accuracy or speed baseline.",
            "prompts": [{"id": "demo-%03d" % (i*10+j+1), "text": task.format(topic)}
                        for i, topic in enumerate(topics) for j, task in enumerate(tasks)],
            "warmups": ["Explain the integer %d in one short sentence." % i for i in range(1, 17)]}

if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    data = (json.dumps(content(), ensure_ascii=False, indent=2) + "\n").encode()
    (ROOT / "corpus.json").write_bytes(data)
    (ROOT / "corpus.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")