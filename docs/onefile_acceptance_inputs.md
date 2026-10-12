# 在另一部 Windows 驗收同一顆 EXE

驗收工具需要完整的同一批建置材料。只取得 EXE 與測試矩陣並不足夠。
這是工程驗收工具；一般使用者執行 TaxOps 不需要這些額外收據或 Python。

## 準備材料

1. 核對下載產物的大小與 SHA-256，保留原始 ZIP。
2. 使用該產物記錄的原始碼 commit／tree，保持 checkout 乾淨；相同 tree
   但不同 commit 也不能冒稱同一筆來源證據。
3. 從同一份產物取得：
   - 真正的單檔 `TaxOpsControlDesk.exe`，不是 payload-inspection 內的邏輯檢視檔。
   - `source-tests/matrix.json` 與其完整來源測試證據。
   - `build-staging/windows-system-runtime.json`。
   - `build-staging/official-vc.json`。
   - `build-staging/package-environment.json`。
   - `build-staging/windows-staging-input.json`。
   - `build-staging/windows-staging-dependencies.json`。
4. 使用既定版本的 release Python 環境，指定全新的輸出目錄。

```text
python -m build_tools.verify_onefile --exe "<原產物中的單檔 EXE>" --source-matrix "<原產物>/source-tests/matrix.json" --build-staging "<原產物>/build-staging" --output "<全新驗收目錄>"
```

不必將外部收據複製進 checkout 的 artifacts 目錄。省略 `--build-staging`
時，仍使用 checkout 的 `artifacts/build-staging`，供原本的建置流程使用。
材料缺少、空白、不可讀或不是一般檔案時，工具會一次列出需補齊的項目，
保存 failed provenance，並在啟動 EXE 前停止。既有輸出目錄不會被覆寫。

## 核對順序及信任邊界

- 完整來源矩陣仍要求相符的原始碼 identity、全部測試檔、零失敗／略過／未跑，
  以及未四捨五入的至少 90% 分支覆蓋率。
- 檢查新解出的實際 payload，將五份收據與來源、封裝檔案清單、雜湊和大小對齊。
  系統 runtime schema 2 以同目錄相對檔名及雜湊連結環境、完整 staging 清單與
  dependency 證據；不能以另一份根目錄下的收據補足缺件，也不能將舊 schema 1
  的成功當作新資料齊全。
- 官方 VC 收據必須包含固定來源的五個成員、原始簽章程序證據、完整且不重複的
  八個 Qt／Shiboken 目的地；另外兩個 Python VC 仍由原有完整 payload 規則檢查。
- 收據中的 `Valid` 文字不是新的信任證明。工具會在目前 Windows 主機，使用原有
  Authenticode 方法再次核對五種精確 payload bytes，分開記錄原 builder 收據及
  本次主機的簽章結果。它不執行收據內的舊命令，也不要求舊主機的 TEMP 路徑存在。
- Windows 的信任鏈查詢是建置／驗收行為，不能混稱為應用程式 18 項自測的
  `network_attempts=[]` 證據。一般使用者的離線核心執行契約不因此改變。
- 所有必要輸入在執行前及結束時再次核對未被改動。輸入檔案雜湊保存在新的
  `onefile-provenance.json`；此收據不會改寫原主機的失敗結果。
- 目前主機重新解析原生依賴的三份證據只寫入新輸出目錄的
  `current-host-native-proof`，原下載材料目錄全程只讀；既有的同名報告不會被覆寫。

第二主機要重新執行完整的封裝、系統提供者、啟動、雙開、本人中止碼 77、
重啟資料保留、18 項功能及實際載入來源驗收，不能挪用第一主機的 runtime 報告。
來源測試與第二主機 runtime 證據分列；通過某部主機也不代表所有乾淨 Windows
版本、輸入法、縮放或印表機都已驗證。

目前變更須由新的固定來源 Windows CI 及實際 EXE 執行驗證；Linux 合成契約
測試不是 Windows 簽章或 EXE 驗收結果。
