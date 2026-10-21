import argparse
from pathlib import Path

import openvino as ov
import torch
from openvino_tokenizers import convert_tokenizer
from transformers import AutoModel, AutoTokenizer

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
torch.set_num_threads(4)
tokenizer = AutoTokenizer.from_pretrained(args.source, local_files_only=True)
model = AutoModel.from_pretrained(
    args.source, local_files_only=True, torch_dtype=torch.float32,
    attn_implementation="sdpa", reference_compile=False,
).eval()


class Encoder(torch.nn.Module):
    def __init__(self, encoder):
        super().__init__()
        self.encoder = encoder

    def forward(self, input_ids, attention_mask):
        return self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state


example = tokenizer("Compare REST and GraphQL APIs.", return_tensors="pt")
with torch.no_grad():
    ir = ov.convert_model(
        Encoder(model),
        example_input=(example["input_ids"], example["attention_mask"]),
        input=[("input_ids", ov.PartialShape([1, -1])), ("attention_mask", ov.PartialShape([1, -1]))],
    )
args.output.mkdir(parents=True, exist_ok=True)
ov.save_model(ir, args.output / "openvino_model.xml", compress_to_fp16=False)
ov.save_model(convert_tokenizer(tokenizer), args.output / "openvino_tokenizer.xml")
tokenizer.save_pretrained(args.output)
print("Exported full 22-layer mmBERT FP32 IR; runtime will use BF16 for both AMX modes.", flush=True)