#!/usr/bin/env bash
set -euo pipefail
case "${SR_AMX_MODE:?SR_AMX_MODE must be on or off}" in
  on) isa=AVX512_CORE_AMX ;;
  off) isa=AVX512_CORE_BF16 ;;
  *) echo 'SR_AMX_MODE must be on or off' >&2; exit 2 ;;
esac
if [[ "$SR_AMX_MODE" == on ]] && ! grep -qw amx_bf16 /proc/cpuinfo; then
  echo 'AMX BF16 is not exposed by this CPU/OS' >&2; exit 2
fi
export ONEDNN_MAX_CPU_ISA="$isa" DNNL_MAX_CPU_ISA="$isa"
export OPENVINO_CACHE_DIR="/tmp/openvino-cache-$SR_AMX_MODE"
export EMBEDDING_BACKEND_OVERRIDE=openvino AI_BINDING=openvino
echo "SR_AMX_REQUESTED mode=$SR_AMX_MODE isa=$isa backend=openvino precision=bf16"
exec /app/router-openvino --config "${CONFIG_FILE:-/app/config/config.yaml}" "$@"