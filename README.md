# Kitajimacro

Windows 11とUbuntu Desktop向けのキーボード・マウス割り当てアプリです。

## 起動

- **Windows** — .NET 10 SDKを入れ、[BuildAndRun.bat](BuildAndRun.bat) をダブルクリックします。
- **Ubuntu Desktop 24.04 LTS以降** — 初回はリポジトリ直下で次を実行します。以降は `./BuildAndRun.sh` だけで起動できます。

```bash
sudo apt update
sudo apt install python3-gi python3-evdev python3-pyudev gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 wl-clipboard xclip
sudo ./ubuntu/setup-input.sh
./BuildAndRun.sh
```

起動スクリプトを実行すると、常駐中の旧プロセスを終了して設定画面を開きます。Ubuntuの入力権限は、対象デバイスを同じユーザーのプロセスからも利用できるようにします。設定後に接続できない場合は再ログインしてください。通知領域にはAppIndicator対応が必要です。

## 使い方

1. 通常またはSKレイヤーで「＋ 追加」を選び、キー・マウスボタン・縦ホイールを選びます。「入力を取得」から直接指定できます。
2. 「入力の置き換え」「シーケンス」「SKキー」を選んで保存します。通常レイヤーでSKキーを指定すると、押している間だけSKレイヤーに切り替わります。
3. **F12** で有効・停止を切り替え、**Esc** で実行中のシーケンスを中止します。「ショートカット設定」でキー・マウスボタン・縦ホイールに変更できます。「例を追加」から繰り返しのサンプルを試せます。

- シーケンスの実行モードは「1回」「停止入力まで」「指定回数」「押している間」の4種類です。「押している間」は割り当て元を離すと実行途中でも止まります。縦ホイールにはほかの3種類を指定できます。
- 「押して離す」は待ち時間なしで押下と解放を送ります。押下時間が必要な操作には「長押し」を使えます。
- 一覧やステップは **Delete** で削除し、**Ctrl+Z／Ctrl+Y** で取り消し・やり直しできます。ステップは **Ctrl+C／Ctrl+V** で別のシーケンスに貼り付けられます。
- 「IME On」「IME Off」は割り当て元・変換先・シーケンスで選べます。出力先では対応する日本語IMEを選択してください（Windowsは Microsoft IME、Ubuntuは IBus + Mozc など）。
- 設定画面を閉じると常駐します。通知領域の「設定を開く」「終了」「サインイン時に自動起動」で操作できます。
- コマンドはWindowsでは `cmd.exe`、Ubuntuでは `/bin/sh` を使います。Ubuntuの文字入力はクリップボードと **Ctrl+V** を使います。

## 設定を共有する

「エクスポート」で保存した共通JSONを、別のPCの「インポート」で開きます。WindowsとUbuntuの間で双方向に共有でき、互換性のあるキーが対象です。インポートには信頼と免責への同意が必要で、取り込み後はマクロが停止します。ショートカットはPCごとに保存されます。「指定回数」または「押している間」の設定を共有するときは、両方のPCでこの機能に対応する版を使ってください。

コマンドを含む割り当ては既定で除外します。実行環境が異なるコマンドも割り当てごと除外します。保存先はWindowsが `%LOCALAPPDATA%\KeyMacro\bindings.json`、Ubuntuが `~/.config/kitajimacro/bindings.json`（`XDG_CONFIG_HOME` があればその配下）です。
