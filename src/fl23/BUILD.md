# 原生模組與可重現檢查

> 历史组件／研究记录。当前修复分支的命令、构建和验证方法以[开发指南](../../docs/zh-CN/development.md)为准。来源署名与许可继续保留。

`assets/manifest.json` 固定每個實際部署資產的SHA-256。`native/` 包含原生AArch64程式與固定窗口表；`installer.c` 的本機資料指標需要80個 ELF RELATIVE 重定位，由機內正常載入器處理。沒有外部符號或 DT_NEEDED 相依庫。原生診斷、WBI及執行期讀取模組沒有動態相依或重定位。

參考交叉編譯器為 Zig 0.13.0：

```text
zig cc -target aarch64-linux-gnu -shared -fPIC -O2 -ffreestanding -fno-builtin -fno-stack-protector -fno-unwind-tables -fno-asynchronous-unwind-tables -nostdlib -Wl,--no-undefined -Wl,-Bsymbolic -Wl,-z,noexecstack -o installer.so native/installer.c
```

以相同參數分別編譯 `probe.c`、`wbi.c`、`runtime.c`。`runtime.c` 包含 `probe.c`。工具鏈差異可能造成輸出位元組不同；檔案不同不能直接通過舊的資產雜湊，須重新驗證程式並更新清單。

## 0.5.0：只改資料時的等長位元組同步

`patch_manifest.h` 是由 `assets/patches.json` 產生的（`work/tools/build_fl23_050.py`）。當改動只落在**長度不變**的資料視窗時（0.5.0 的 Gamma 視窗仍是 3872 位元組），不必重新編譯：`new_0`（3872B）與 `final_hashes[1]`（32B）在 `installer.so` 中各只出現一次，可原址覆寫。模組大小維持 56864 位元組，ELF 重定位不受影響。若要重新編譯，上面的 `zig cc` 指令仍然適用，但工具鏈會讓整個模組的位元組不同，需重新驗證並更新 `assets/manifest.json`。

`tests/test_gamma.py` 固定了「模組大小不變、`new_0` 只出現一次、四筆完整檔案雜湊都在模組內」這三件事。

安裝Python依賴後，可執行 `python -m unittest discover -s tests -v` 與 `python app.py check-package`，都不連線相機。

本套件的可攜Python流程尚未在第二台機身驗證；原生工作程式與固定窗口是在一台目標機身完成寫入及完整讀回的版本。離線測試不等於第二台實機測試。
