# Daily Architecture Paper Bot

每天從 arXiv、DBLP、Crossref 與可選的 IEEE Xplore API 搜尋電腦架構論文，優先選擇 ISCA、MICRO、HPCA、ASPLOS 最新且尚未推送的文章。程式只使用公開或目前網路環境可直接取得的 PDF，不會登入網站、繞過付費牆或處理 CAPTCHA。全文由 Gemini 模型池摘要成繁體中文，再透過 LINE Messaging API 傳送。

## 功能

- 聚合多個 metadata 來源，並以 DOI、arXiv ID 與標題合併重複資料。
- 優先挑選符合 GPU/GPGPU 等偏好關鍵字的頂會論文。
- 自動嘗試來源 PDF、DOI landing page 與相符的 arXiv 公開版本。
- Gemini 模型失敗時依設定順序切換模型。
- 使用 SQLite 保存候選論文、摘要、傳送狀態與失敗紀錄。
- LINE 傳送失敗時保留摘要，之後可直接重送，不會再次消耗摘要額度。

## 系統需求

- Linux、Python 3.12+
- Poppler `pdftotext`
- Gemini API key
- LINE Official Account 的 Messaging API Channel Access Token
- 你的 LINE User ID（LINE Developers Console 的 channel「Basic settings」可查看自己的 User ID）
- 聯絡 email，供 arXiv/Crossref/DBLP 的 User-Agent 與 polite pool 使用
- IEEE API key 為選填；未設定時仍會使用 DBLP、Crossref 與 arXiv
- systemd user service（只有啟用每日排程時需要）

## 安裝

```bash
git clone git@github.com:yugalin66/DailyPaper.git
cd DailyPaper
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
chmod 600 .env
```

編輯 `.env`，至少填入：

```dotenv
GEMINI_API_KEY=...
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_USER_ID=U...
CONTACT_EMAIL=your-email@example.com
```

`IEEE_API_KEY` 是選填項目。`.env` 已列入 `.gitignore`，請勿把任何 API key、access token 或 LINE User ID 寫入 README、程式碼或提交紀錄。

## 設定

論文偏好關鍵字預設為 GPU 與 GPGPU：

```dotenv
PAPERBOT_PREFERRED_KEYWORDS=GPU,GPGPU
```

排序順序為「含偏好關鍵字的頂會論文 → 其他頂會論文 → 含偏好關鍵字的一般論文 → 其他一般論文」。匹配範圍包含標題與摘要，也會接受 `GPUs` 等複數形式。

預設模型順序為：

```dotenv
GEMINI_MODELS=gemini-3-flash-preview,gemini-3.5-flash,gemini-2.5-flash
```

Gemini Preview model ID 可能改名。可用以下指令驗證 API，並依 Google AI Studio 實際列出的 model ID 修改設定：

```bash
.venv/bin/paperbot healthcheck --online
```

## 手動執行

```bash
# 僅驗證本機設定
.venv/bin/paperbot healthcheck

# 跑完整搜尋與摘要，但不傳 LINE
.venv/bin/paperbot dry-run

# 正式傳送一篇
.venv/bin/paperbot run

# LINE 傳送失敗後，重送已保存的摘要（不重跑 AI）
.venv/bin/paperbot retry
```

`dry-run` 仍會呼叫論文來源與 Gemini，因此會消耗 API quota；它只不會傳送 LINE 或將摘要標記為已傳送。

## 啟用每日 09:00 排程

`deploy/paperbot.service` 預設專案位於 `/home/yuga/Desktop/PaperBot`。若 clone 到其他位置，先修改 service 內的 `WorkingDirectory`、`EnvironmentFile` 與 `ExecStart`。

```bash
mkdir -p ~/.config/systemd/user
cp deploy/paperbot.service deploy/paperbot.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now paperbot.timer
systemctl --user list-timers paperbot.timer
```

排程使用 `Asia/Taipei`、`Persistent=true`。若 09:00 電腦關機，會在下次 user systemd manager 啟動時補跑。若希望登出後 user service 仍保持啟用，可執行：

```bash
loginctl enable-linger "$USER"
```

查看執行紀錄：

```bash
journalctl --user -u paperbot.service -n 100 --no-pager
systemctl --user status paperbot.timer
```

## 選文與失敗處理

1. 聚合最近十年的頂會 metadata，並加入最新 arXiv `cs.AR` 論文。
2. DOI、arXiv 與標題資料會合併；已成功傳送的論文不再選取。
3. 優先依 ISCA、MICRO、HPCA、ASPLOS 的出版日期選最新未讀論文。
4. 依序嘗試來源 PDF、DOI landing page 的 `citation_pdf_url`、校園 IP 可直接下載的版本，以及標題高度相符的 arXiv 公開版本。
5. 找不到可解析全文就改選下一篇，最多嘗試 20 篇。
6. Gemini 模型各嘗試三次後才切換下一模型。
7. 摘要先寫入 SQLite，再傳 LINE；LINE 失敗時下次執行只重送原摘要。

資料庫位於 `data/paperbot.sqlite3`，暫存 PDF 在解析後自動刪除。API 金鑰只存放於權限為 `0600` 的 `.env`。

## 開發與測試

```bash
.venv/bin/pytest
```

測試不得呼叫真實的論文來源、Gemini 或 LINE API；請 mock HTTP、sleep 與外部服務。提交前也應確認 `.env`、`data/`、logs、PDF 與其他本機 runtime 檔案沒有被 Git 追蹤。
