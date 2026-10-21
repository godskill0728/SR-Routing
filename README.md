# SR Routing：OpenVINO AMX ON／OFF 與即時 Demo Portal

這是 **SR Demo 的公開可攜來源套件**，不是完整 upstream mirror。以 2026-10-21 只讀擷取的應用程式為基礎，入口為 [portal/fill_release.py](portal/fill_release.py)；來源識別與原始雜湊保留於 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。公開版已將操作環境識別改為範例值，並非原部署的逐位元複本。整理過程沒有修改原來源或部署。

## 架構與目前功能

瀏覽器 → Python 標準函式庫 Portal → ON／OFF 各自的 Envoy → Semantic Router `ext_proc` → LiteLLM → OpenAI 相容模型服務。

SR-only 比較則由 Portal 呼叫兩側 `/api/v1/eval`，不生成 LLM 回答。三種難度對應 Qwen3.5-4B、Gemma-4-12B、Qwen3.8-27B-FP8 的模型別名。OpenVINO 原生 embedding 共用 BF16 精度，以 ISA 上限區分 ON／OFF。

- 保留單次串流比較、短效 trace capability、Jaeger 階段時間查詢。
- 保留批次、平行工作池、C15 選項、真實請求完成曲線、取消／lease／錯誤處理。
- 保留白色圖表、英文 UI、軸線 profiles、fullscreen／fit／fill 及全部 wrapper 相依鏈。
- 歷史報表 allowlist 改用通用路徑及檔名，不承諾原 URL 相容性；未打包的檔案明確回傳 404，報表首頁說明排除原因。
- 合成 100 題與 16 題暖身題僅供操作示範；**不是現行部署原題庫，不得用來重現歷史量測**。原軸線 profiles 只是 UI 預設，不代表新硬體效能。
- ON／OFF 標籤不是逐請求 AMX kernel 證據；共享 CPU 的完成時間也不是獨立因果加速比。

## 本機啟動

Python 3.10+；Portal 本身無第三方套件。在本儲存庫根目錄執行：

```sh
python3 -B portal/fill_release.py
```

開啟 http://127.0.0.1:8080/compare/ 。預設僅監聽 loopback，所有上游指向 loopback 的 port 9，管理模式切換停用；可正常瀏覽 UI，不會自動送出模型請求。此預設假設本機 port 9 沒有服務。[.env.example](.env.example) 是環境變數清單，Python **不會自動載入環境檔**；請透過 shell／服務管理員設定。修改 `PORT` 可選擇其他埠。

需要連接經授權的測試系統時，設定 `ENVOY_URL_ON/OFF`、`EVAL_URL_ON/OFF`、`ROUTER_HEALTH_URL_ON/OFF`；可選 `JAEGER_TRACE_URL`。URL 不得嵌入使用者名稱／密碼。送出比較會產生實際負載，必須事先取得容量授權。`REPORTS_ROOT` 可掛載經審查的報表；替換題庫時必須明確設定其 `CORPUS_SHA256`。

**不要直接對外開放 Portal。** 舊 `/api/stream` 沒有應用層 authentication、明確的 body 大小／token 上限或共享並行額度；比較 API 的界限不會自動保護此路由。接上上游前須以 ingress authentication、TLS、body／timeout／rate／concurrency 限制及網路隔離保護；不需要舊 chat 時在 ingress 封鎖該路由。詳見 [SECURITY.md](SECURITY.md)。本套件保留既有 chat 行為，未另作 authentication gateway 改造。

## 測試與安全檢查

安裝 Python 開發依賴；另外需要 Node.js 與 Helm 3：

```sh
python3 -m pip install -r requirements-dev.txt
python3 -B tools/validate.py
```

本套件本機驗證：**77 tests、10 個 JS syntax checks、Helm lint 與完整 render 11 resources 全部 PASS**。另已獨立執行 **gitleaks 8.30.1 directory scan，PASS／0 findings**，包含初始匯出 artifacts 與最後清理後套件；不是僅掃描 Git 已追蹤檔案。掃描不保證找出所有敏感資料，後续變更仍須重驗。詳細範圍見 [VALIDATION.md](VALIDATION.md)。

驗證使用假 eval、loopback 暫時埠、記憶體 Python compile、原始／渲染後 JS 的 `node --check`、Helm lint／完整 render，以及只輸出路徑／行號／規則的憑證啟發式掃描。測試以分開 process 執行，避免歷史 wrapper 的 import-time patch 互相污染。

## 容器與 Kubernetes

```sh
docker build -t sr-routing-portal:reviewed .
docker run --rm -p 127.0.0.1:8080:8080 sr-routing-portal:reviewed
helm template sr-demo deploy/chart
```

Chart 預設只部署 Portal，沒有叢集管理 RBAC、hostPath 或 ServiceAccount token，Service 為 ClusterIP。審查後可使用自己的 registry image 及 `helm upgrade --install`；不應直接套用至既有正式環境。NodePort 32468 是選配：設定 `portal.serviceType=NodePort`，先確認沒有與現行 Demo 衝突。

完整 stack 是**需外部資源的部署範本**，不是已執行驗證的 turnkey native build：

1. 先按照 [native/README.md](native/README.md) 建置並審查 router image；準備自行選定的 LiteLLM image。
2. 準備模型 PVC：根目錄須含 `models/`（router 模型資源）與 `openvino-model/`（IR／tokenizer）；模型權重與授權由使用者取得，本套件不含權重。
3. 由 Secret manager／管理員在目標 namespace 建立 `sr-backend-credentials`，提供 `PROXY_MASTER_KEY`、`EASY_API_BASE/API_KEY`、`MEDIUM_API_BASE/API_KEY`、`HARD_API_BASE/API_KEY`。三個 BASE 是含 `/v1` 的 URL。SR 從同一 Secret 引用 `PROXY_MASTER_KEY` 為 `LITELLM_API_KEY`；沒有預設 key 或 Secret YAML。
4. 產生非敏感 config values，review 後再部署：

```sh
mkdir -p .generated
python3 -B tools/render_values.py --release sr-demo > .generated/configs.yaml
helm template sr-demo deploy/chart -f .generated/configs.yaml \
  --set stack.enabled=true \
  --set stack.routerImage=YOUR_REGISTRY/sr-openvino:reviewed \
  --set stack.litellmImage=YOUR_REGISTRY/litellm:reviewed \
  --set stack.modelPVC=sr-models
```

Renderer 保留難度／模型／Envoy routing 邏輯，改為 release-local DNS，Envoy extproc 改 loopback（同 Pod），admin 僅 loopback。tools 預設關閉且資料庫為空；tracing 預設關閉。需要 Jaeger／Langfuse 時，先外部配置憑證，再審查生成配置中的 tracing endpoint、sampling 與 callback；不會自動套用。

原始範例 backend 為 `sr-demo-litellm:4000`，renderer 依 `--release` 改為 `<release>-litellm:4000`。Tracing endpoint 是不可部署的 `jaeger.example.invalid:4317`；啟用前自行替換。邏輯 trace service 名稱固定為 `sr-demo-on`／`sr-demo-off`，**不是依 Helm release 改名的 DNS**；Portal 以此作嚴格 ON／OFF 比對。若自訂 tracing `service_name`，同步設定 Portal 的 `TRACE_SERVICE_ON/OFF`，否則 trace timing 會拒絕錯配而非混用兩側。

`stack.cpuSetOn/Off` 是明確選配的 `taskset` cpuset；須先確認 image 含 taskset、節點 CPU topology、cgroup 可用範圍與排程策略。CPU requests／limits 不等於獨占 CPU；此 chart 不聲稱已重現原部署 socket placement。

## 來源、授權與排除

- Portal：31 個擷取的 application keys（含必要 JSON），按原 mount 的平面布局保存。可攜、安全及通用報表路徑調整逐檔記錄於 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。
- Native：完整小型 OpenVINO binding 原始碼、4 個有變更的 Go bridge／classifier 檔案、build recipe、model export、兩個可選診斷 C++。未 vendor 完整 upstream／Git／binary；見 [native/README.md](native/README.md)。
- Routing：ON／OFF 設定改用範例 service DNS，保留不同模型的 header match／cluster 對應；LiteLLM 使用外部環境引用版，沒有原始 API keys、endpoint IP 或 callbacks 憑證。
- Deploy：本套件自有精簡 chart；不複製巨大的 upstream values、舊部署快照或 Secret manifests。
- Observability：dashboard builder、dashboard／ScrapeConfig 範本改用範例 datasource／namespace／selector／ON／OFF targets，並保留純測試及 read-only native evidence sidecar；見 [observability/README.md](observability/README.md)。
- 不含一鍵生產變更脚本、manager provisioning、歷史 report／CSV／trace／payload／prompt、模型、archive、私有 baseline、credentials、CSE／Pega 或可選 flow explorer。

[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) 記錄擷取 UTC、原相對路徑或 ConfigMap key／版本、原始來源 SHA-256、輸出 SHA-256／bytes、修改旗標及原因。原來源識別僅作 provenance，不是部署預設。無法從本機「0.3.0」目錄名證實完整 Git commit，因此 native build 會檢查已知原始 base hashes，**不聲稱可由任意同名 tag 重建線上 digest**。Native build／真實推論及 live integration 尚未驗證。

上游 Apache-2.0 授權全文保留於 [native/UPSTREAM-LICENSE](native/UPSTREAM-LICENSE)，既有標頭不變。自訂 Portal／整合程式碼的發布授權由 repository owner 決定；本次整理不另行新增或推定授權。