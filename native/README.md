# Native OpenVINO overlay

此處不是完整 upstream mirror。來源比較發現原始封存版與現有 tree 的 5 個差異：embedding_generator.cpp，以及 classification 下 4 個 Go 檔。另保留小型 binding 的 C++／header／Go／CMake／conversion scripts，方便單獨審查與 build。原授權與標頭保留，未杜撰 commit 或自訂程式授權。

## 建置步驟與限制

1. 從 https://github.com/vllm-project/semantic-router 取得並審查相容 upstream checkout。`upstream-base-hashes.json` 是原始封存版的 base-file hashes，不是機密 baseline；目錄名 v0.3.0 不足以認定 Git revision。
2. 執行 `python3 -B native/prepare_context.py /path/to/reviewed/upstream`。它先驗證 5 個 base files，再複製到忽略的 build context，套用 overlay；不修改 supplied checkout、不下載也不繞過 mismatch。若失敗，先確認來源版本。
3. 依 upstream build requirements 建置 `candle-binding`、`onnx-binding`、`ml-binding`、`nlp-binding`，將生成的 `libcandle_semantic_router.so`、`libonnx_semantic_router.so`、`libml_semantic_router.so`、`libnlp_binding.so` 及動態相依庫放入忽略的 `native/native-libs/`。它們不是本套件提供的 prebuilt binaries；各 Rust crate 的 Cargo／upstream build recipe 為準。
4. 執行 `docker build -t sr-openvino:reviewed native`。保留的 Dockerfile 使用 Go 1.24.13、OpenVINO／tokenizers 2025.4.0、transformers 4.57.6、CPU torch 2.7.1；CMake 建置 OpenVINO shared library，Go 以 `-tags=openvino` 連結。**此次整理未執行此重量級 build，也未驗證完整動態庫閉包或 registry digest。**
5. 在相同 Python 套件環境，以 `python export_model.py /path/to/local/model /path/to/output` 轉換自行取得並授權的模型。它使用 local-files-only，不會下載權重；輸出完整 encoder IR／tokenizer，不是測試 stub。

entrypoint 以 `SR_AMX_MODE=on/off` 設定 ONEDNN／DNNL ISA 上限；ON 要求 CPU 暴露 amx_bf16。BF16 精度、thread／stream／request pool knobs 與 native executed/amx-node evidence 寫檔邏輯保留。不能只憑 mode label 證明某次運算使用 AMX。

diagnostics/ 是可選診斷 interposer：不會自動 build／preload，也不由 chart 載入。尤其 pinning_off 會改變執行條件，只適合明確授權的實驗，不作預設 runtime。