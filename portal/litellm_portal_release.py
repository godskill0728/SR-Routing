"""Additive UI entrypoint: SR selects the model BEFORE LiteLLM calls vLLM.

Import the portable report allowlist chain first. Do not wrap request handlers,
change destinations, add credentials, or initialize a tracing SDK here.
The actual live page symbol is INDEX_HTML (there is no served HTML symbol).
"""
import streams_contrast_release  # noqa: F401 -- allowlists only; reports excluded
import portal_server


CALL_ID_HEADER = "x-litellm-call-id"

REPLACEMENTS = (
    (
        '  <div class="composer">',
        '''  <section class="amx-card" aria-labelledby="litellm-path-title" lang="en">
    <h2 id="litellm-path-title">SR → LiteLLM → vLLM</h2>
    <p class="amx-copy">Request path after routing integration: Portal → selected SR (AMX ON / OFF) → LiteLLM → vLLM. SR chooses the model; LiteLLM handles the downstream LLM call. The existing per-request ON / OFF selection is unchanged.</p>
    <p class="amx-copy">SR model → LiteLLM alias:</p>
    <ul class="amx-copy" style="overflow-wrap:anywhere">
      <li>qwen3.5-4b-l4 → Qwen3.5-4B</li>
      <li>gemma-4-12b → gemma-4-12B</li>
      <li>qwen3.8-27b → Qwen3.8-27B-FP8</li>
    </ul>
    <p class="amx-copy">Trace scope: when configured, LiteLLM emits the Langfuse LLM observation for its downstream model call. This is not Portal end-to-end timing and does not measure SR classification. A LiteLLM call ID, if forwarded, is a correlation identifier—not a Langfuse trace ID or proof that an observation was exported. No timing or cost is inferred here.</p>
  </section>
  <div class="composer">''',
    ),
    ('3 · vLLM 後端', '3 · LiteLLM → vLLM'),
    (
        '''const BACKENDS = {
  "qwen3.5-4b-l4": { name:"Qwen3.5-4B", gpu:"L4 GPU" },
  "gemma-4-12b":   { name:"Gemma-4-12B", gpu:"H100" },
  "qwen3.8-27b":   { name:"Qwen3.8-27B", gpu:"H100" },
};''',
        '''const BACKENDS = {
  "qwen3.5-4b-l4": { name:"Qwen3.5-4B", gpu:"L4 GPU", alias:"Qwen3.5-4B" },
  "gemma-4-12b":   { name:"gemma-4-12B", gpu:"H100", alias:"gemma-4-12B" },
  "qwen3.8-27b":   { name:"Qwen3.8-27B-FP8", gpu:"H100", alias:"Qwen3.8-27B-FP8" },
};''',
    ),
    (
        '    const b = BACKENDS[key];',
        '    const b = Object.hasOwn(BACKENDS, key) ? BACKENDS[key] : Object.values(BACKENDS).find(item => item.alias === key);',
    ),
    (
        '    el.mdl.textContent = b ? b.name + " · " + b.gpu : (key || "—");',
        '    el.mdl.textContent = b ? b.name + " · " + b.gpu + " · LiteLLM alias: " + b.alias : (key || "—");',
    ),
    (
        '      " · max_tokens=" + obj["max_tokens"];',
        '''      " · max_tokens=" + obj["max_tokens"];
    const callId = obj["x-litellm-call-id"];
    // Only an opaque, bounded identifier; never HTML, a URL, timing, or a trace link.
    const safeCallId = typeof callId === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(callId) && callId.trim() === callId;
    el.metaline.textContent += " · LiteLLM call ID: " + (safeCallId ? callId : "not available");''',
    ),
)


def patch_html(original):
    """Fail closed on drift; apply only six unique, reviewed live-source anchors."""
    if not isinstance(original, str):
        raise RuntimeError("Expected portal_server.INDEX_HTML text")
    for index, (old, _new) in enumerate(REPLACEMENTS):
        if original.count(old) != 1:
            # Do not include source or response data in error messages.
            raise RuntimeError(f"Portal UI anchor {index} missing or duplicated")
    updated = original
    for old, new in REPLACEMENTS:
        updated = updated.replace(old, new, 1)
    return updated


# Validate before either mutation. Keep the existing header-list object and order.
_updated_html = patch_html(portal_server.INDEX_HTML)
if not isinstance(portal_server.VSR_HEADERS, list) or not all(
    isinstance(header, str) for header in portal_server.VSR_HEADERS
):
    raise RuntimeError("Expected portal_server.VSR_HEADERS string list")
portal_server.INDEX_HTML = _updated_html
if CALL_ID_HEADER not in portal_server.VSR_HEADERS:
    portal_server.VSR_HEADERS.append(CALL_ID_HEADER)


if __name__ == "__main__":
    portal_server.main()