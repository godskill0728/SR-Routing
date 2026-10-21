# 安全與發布審查

- 本機預設 loopback、上游 loopback port 9（假設無服務）、AMX 管理切換停用。公開服務前在 ingress 加上 authentication、TLS、rate／concurrency limit、request size／timeout 與網路限制。Portal 不是多租戶 authentication gateway。
- 舊 `/api/stream` 保留原有行為：沒有應用層 authentication、明確的 request-body 大小／token 上限或共享並行閘門，且上游錯誤可能回傳 detail。比較／批次 API 的額度並不涵蓋此路由。未配置上述 ingress 保護時不得連接可用上游並對外開放；不需要舊 chat 時在 ingress 封鎖它。預設 loopback 不是連接正式上游後的資源隔離保證。
- API keys 只能經外部 Secret manager／環境變數提供，不要貼入 issue、報表、shell history 或 commit。沒有預設 admin／password／manager token。
- Chart 只引用既存 Secret，不建立 Secret；來源擷取只 GET Deployment／ConfigMap，從未 GET Secrets。不要將完整 Kubernetes objects、last-applied annotations、kubeconfig 或環境 dump 放入 repository。
- 歷史憑證 provisioning 與一次性叢集變更工具完全排除。Portal 內網 fallback、routing／Envoy 的操作環境 DNS、observability 識別及歷史報表主機／日期路徑均改為公開範例。LiteLLM 用環境引用版，不複製 live key 值。原始相對路徑與擷取識別僅保留於 manifest provenance；並非 runtime 設定。
- [tools/audit_sources.py](tools/audit_sources.py) 僅輸出檔案／行號／rule，不列疑似內容。獨立 **gitleaks 8.30.1** directory scan 已完成，初始 artifacts 與最後清理後套件均 **PASS／0 findings**，使用 `--redact=100`。它不依赖 Git tracking，也不保證識別所有憑證或私有識別；後續變更須重新掃描及人工覆核。
- [.gitignore](.gitignore) 不是資料外洩防護：刻意 force-add 可以繞過。請檢查所有發布內容及 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)，尤其 app keys、原生 overlay 與 router examples。原始來源雜湊不會被輸出檔案雜湊取代。
- 本套件離線驗證為 77 tests、10 JS checks、Helm render 11 resources；未做真實 LLM／eval、native image build 或 Helm install。請勿解讀成 live integration／效能驗證。詳見 [VALIDATION.md](VALIDATION.md)。