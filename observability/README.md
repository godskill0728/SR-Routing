# SR observability

保留 dashboard builder、32 panels dashboard、ScrapeConfig 範本及 8 個純單元測試，沒有 production ops／apply scripts。公開範例使用 datasource UID／Prometheus release selector `example-prometheus`、namespace `default`、ON／OFF targets `sr-demo-on:9190`／`sr-demo-off:9190`，不含來源環境的操作識別。Dashboard 的歷史 coverage 說明仍是量測邊界，不表示本套件已部署 collector。

部署前修改 [observability/build.py](build.py) 的 `DS`、`resources()` targets／namespace／labels，對應自行部署的 datasource、Prometheus selector 及 chart release。本 chart 目標為 `<release>-on:9190` 與 `<release>-off:9190`；範例假設 release `sr-demo` 且同 namespace，跨 namespace 應使用自己服務的完整 DNS。在新的輸出目錄生成並審查，勿直接覆寫既有 artifacts；可 import build 並呼叫 `resources()` 後自行寫出。預設 main 拒絕覆寫不同內容，且不呼叫 Kubernetes。套件測試逐項比較 [observability/dashboard.json](dashboard.json)／[observability/scrapeconfig.json](scrapeconfig.json) 與 builder，並確認兩侧 target 不相同。

native_evidence.py 只讀 `/evidence/sr-amx-evidence.json` 並公開白名單欄位，沒有 Secret、推論或叢集控制；是選用 sidecar source，尚未接入本 chart。若使用，需將 router `/tmp` evidence 以 emptyDir 唯讀共享至 sidecar。證據代表最後寫入的 runtime 狀態，非每一筆 Portal request 的嚴格關聯證據。

原生 routing latency、signal latency、Portal HTTP elapsed、LLM completion／TTFT 的範圍不同。錯誤請求可能仍包含在 SR-observed latency；空 quantile 是無樣本，不能填成 0；AMX mode label 不是 AMX 執行證明。