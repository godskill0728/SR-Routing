import argparse
import json
import os
from collections import Counter
from pathlib import Path
from time import perf_counter

import numpy as np
import openvino as ov
from transformers import AutoTokenizer

parser = argparse.ArgumentParser()
parser.add_argument("model", type=Path)
parser.add_argument("--mode", choices=("on", "off"), required=True)
args = parser.parse_args()
expected_isa = "AVX512_CORE_AMX" if args.mode == "on" else "AVX512_CORE_BF16"
assert os.environ.get("ONEDNN_MAX_CPU_ISA") == expected_isa
core = ov.Core()
model = core.compile_model(
    str(args.model / "openvino_model.xml"), "CPU",
    {"INFERENCE_PRECISION_HINT": "bf16", "INFERENCE_NUM_THREADS": 2,
     "NUM_STREAMS": 1, "PERF_COUNT": True},
)
tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
request = model.create_infer_request()
records = []
for text in (
    "What is the capital of France?",
    "Compare REST and GraphQL APIs and explain the trade-offs.",
    "Prove that the sum of any two odd integers is even, with full justification.",
    "Explain distributed database transactions and their failure modes. " * 32,
):
    inputs = tokenizer(text, return_tensors="np")
    # Export preserves encoder argument order; traced ports may have numeric aliases.
    data = {model.input(0): inputs["input_ids"], model.input(1): inputs["attention_mask"]}
    request.infer(data)
    latencies = []
    for _ in range(5):
        start = perf_counter()
        request.infer(data)
        latencies.append((perf_counter() - start) * 1000)
    kernels = Counter(p.exec_type for p in request.profiling_info if p.status == ov.ProfilingInfo.Status.EXECUTED)
    amx_nodes = sum(count for kernel, count in kernels.items() if "amx" in kernel.lower())
    assert (amx_nodes > 0) == (args.mode == "on"), dict(kernels)
    output = request.get_output_tensor().data
    assert np.isfinite(output).all()
    records.append({"tokens": int(inputs["input_ids"].shape[1]), "amx_nodes": amx_nodes,
                    "median_ms": float(np.median(latencies)), "kernels": dict(kernels),
                    "embedding": output.mean(axis=1)[0].tolist()})
print(json.dumps({"mode": args.mode, "isa": expected_isa, "openvino": ov.__version__,
                  "precision": str(model.get_property("INFERENCE_PRECISION_HINT")), "records": records}))