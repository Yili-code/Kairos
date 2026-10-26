# 競賽發現範圍與驗證

## 目前行為

Kairos 監測指定公告與 Threads 關鍵字，並非全網搜尋引擎。2026-10-24 將預設公告入口從 15 個擴充為 21 個；Contest Watchers 改讀仍開放徵件的分類，另加入中央大學職涯中心、經濟系、清華教務處、新北青年局、高雄青年局與 Graphic Competitions。

來源清單位於 `app/config.py` 的 `DEFAULT_ANNOUNCEMENT_URLS`。設定 `ANNOUNCEMENT_SOURCE_URLS` 會整份覆寫預設清單，新增程式預設來源不會自動附加到自訂清單。

- 每輪最多 24 個不重複公告入口；超出時仍每半天輪替。目前預設 24 個可於每輪全數讀取（2026-10-26）。
- 最多四個入口同時處理，每個入口最多讀兩頁，整批受 60 秒期限約束。單一來源失敗或逾時仍保留其他來源結果。
- 下一頁須為相同主機、明確的 next 導覽，並通過既有 HTTPS 與網域檢查。頁碼參數僅接受最多六位數字；登入憑證、任意動作與重複參數仍不接受。
- 支援 HTML meta refresh，沿用既有轉址上限與逐步網址驗證；不執行 JavaScript。
- 標題不必再包含 AI、影片或海報等作品詞。一般提案、挑戰賽、Prize 也可成為線索；體育、明確學術期刊徵稿、得獎回顧與已知目錄導覽會先排除。
- 仍保留每頁最多 20 筆線索及每輪預設三場深入模型評估，沒有為擴大抓取而提高模型額度。

放寬的是發現階段，並非參賽門檻。AI 占比至少 50%、完整資格與期限可行性仍由後續評估檢查；使用者已於 2026-10-26 移除六小時與 NT$300 硬上限，改比較不同時間價值下的成本與回報門檻；未知的 AI 規則與其他必要事實不能因網站被加入而推定符合。

## 可重複的實際抓取

```powershell
.venv\Scripts\python scripts/audit_competition_discovery.py --output work/discovery-audit.json
```

此指令讀取全部設定入口，輸出每頁抓取狀態、去重線索、來源與耗時。它不呼叫模型、不寫入候選資料庫、不傳 Telegram、不寄信、不報名或交件。報告預設存放於已忽略的 `work/`。

2026-10-24 開發驗證曾在一次抓取中取得：21 個入口、22 個頁面請求、21 頁成功、1 頁 HTTP 429、91 筆去重線索、4.31 秒。429 來自神腦基金會公告頁。這是單次觀察，會隨網站內容與限流改變；不是涵蓋率、參賽資格或得獎率的證明。

## 尚未涵蓋

沒有自動的跨網站搜尋、全站爬取或無限翻頁。JavaScript 才能顯示的清單、登入頁、封鎖自動存取的來源與未加入允許網域的主辦網站仍可能漏掉。目錄提供的線索也不代表已讀到主辦方完整規則。

新增來源前先實抓並檢查產出，避免只增加零結果首頁或目錄導覽。新增線索會增加待評估佇列；本次未提高付費模型處理量，也未宣稱已完成所有線索的資格核對。

## 正式部署驗證（2026-10-24）

- 正式版 `kairos-git-00def82` 接收 100% 流量，健康檢查回報 21 個公告入口、每輪三場模型評估，Threads 自動私訊關閉。
- 為保留既有正式功能，部署來源為 `kairos-00028-bay` 的實際原始碼，再套用本次四個程式與文件提交；不是以較舊的 Git 基底覆蓋正式功能。工作區原有未提交內容未納入這些提交。
- 隔離的 Git 變更集通過 168 項測試；實際部署來源通過 181 項測試。
- 使用實際部署來源進行最後一次唯讀抓取：21 個入口、22 頁、21 頁成功、神腦基金會一頁 HTTP 429、97 筆去重線索，耗時 5.23 秒。與前一次數量不同，不能視為穩定每日產量。
- Telegram 已接受一則包含實抓數據的更新及投遞測試通知。這不代表所有線索已經模型核對，也不證明使用者已閱讀通知。

## 2026-10-26 漏收案例修復（部署結果另記）

新增 Devpost 公開活動清單、Unreal Engine 官方 RSS 與 itch.io game jams。這是可持續讀取新活動的入口，不是逐一硬寫 PayPal 或 Epic 的活動網址。預設共 24 個入口，仍在每輪既有上限內；自訂 ANNOUNCEMENT_SOURCE_URLS 仍採整份覆寫，部署前須檢查實際設定。

Devpost 清單使用網站自己引用的公開 JSON 端點；僅允許精確的 open、per_page=20 與有界 page 查詢。每輪讀第一頁與另一個按小時輪替的頁面，最多兩頁，保留 total/pages 診斷。這個端點沒有穩定性承諾；格式改變會揭露 parse_error，不會默認成零活動。清單上的獎金、地點及標籤不構成參賽資格證據。

同一份實抓頁面對照 f81e446 與修正後程式：PayPal（軟體清單）、Epic（官方 RSS 與活動平台兩條路徑）、Cue（影像目錄）原本均漏收，修正後可解析出目標網址。共同修正包含 hackathon／MegaJam／Film Fest 標題、缺少的已核對主辦網域，以及官方 Atom 在 XML 後附加瀏覽器 script 時的解析；script 不執行，非 script 尾端與損壞 XML 仍拒收。

SVAIFF 的目錄目前連向新聞轉述，未提供可直接採用的官方連結；加入官方網域不代表已完成自動發現。Cue 官方網頁是動態頁面，取得連結也不代表完整規則可讀。這些缺口須保留，不能算作已完成查核或已合格推薦。現有來源的 403、429 與來源內未讀頁面仍可能造成漏收。上述樣本不是全網涵蓋率的估計。

Regression fixtures 位於 tests/fixtures/discovery，來自 2026-10-26 官方公開清單／RSS 與既有目錄的精簡欄位。tests/test_discovery_regressions.py 同時驗證格式故障隔離、嚴格查詢、兩頁上限與輪替。實際部署和自然排程證據須獨立記錄。

## Official-rule completeness repair

Read-only comparison across software, games, films and art exposed a second failure after discovery: PayPal and Nebius have about 36–37k characters of page text, so the former 32k per-document cut always marked their official rules incomplete. HTML navigation/footer links also pulled unrelated platform pages into the six-document review budget.

The extractor now ignores navigation/footer copy and external site-wide footer links, while retaining same-event footer terms, rule-navigation links and rules-body references (including explicitly incorporated platform terms). A document can retain 48k characters; the aggregate text budget remains bounded at 192k across at most six documents. Any real truncation or exhausted text budget remains a verification blocker. Complete rule retrieval does not itself establish qualification, effort feasibility or a recommendation.

A JavaScript-only shell with an empty root and only short title text is marked dynamic_rules_unavailable and does not consume a model call as if rules had been read. It stays pending with its fetch receipt; no browser challenge is bypassed, and no organizer is contacted.
