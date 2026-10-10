# 工程別の作業・検証記録

## 02. FastAPI＋Reactの最小構成（2026-10-10）

- 企画書・工程書・ロードマップ・DDLと既存構成を確認。AGENTS.local.mdは存在せず、着手時の作業ツリーに変更なし。
- FastAPIの `/api/health` とビルド済みReactの静的配信を実装。UI未ビルドでもAPIを利用でき、未知のAPI・静的ファイルは404を返す。
- React/TypeScript/Viteの最小画面にAPI接続の成功・失敗を表示。開発時はViteの `/api` プロキシ、配布用ビルドはFastAPIと同じ接続先を使用。APIのアクセス・疎通ログ、ブラウザの接続失敗ログを用意。
- Python依存、npmロックファイル、型検査・フォーマット・テスト・ビルド手順とChromeブラウザ検証スクリプトを追加。READMEと構成資料を更新。最終配布方式は保留のまま、ビルド済みUIとPython APIで起動できる構成とした。
- Python 3.12.4 / Node.js 26.9.0 / FastAPI 0.135.1 / Vite 7.3.7 / Vitest 5.0.3で検証。既存Node.jsをプロセスのPATHへ追加して使用し、システム設定の変更なし。
- APIテスト2件、UIテスト2件、TypeScript型検査、本番ビルド、Ruff検査・書式確認（backend/tests/check_browser.py）、Prettier書式確認に成功。`pip check`、資料構成・リンク検証、`git diff --check` に成功。
- 1920×1080の既存Chrome（ヘッドレス）で、配布用 `http://127.0.0.1:8000` と開発用 `http://127.0.0.1:5173` の両方についてReact表示・ブラウザからAPIへの通信・JavaScript例外なしを確認。
- npm監査で初期テスト依存の脆弱性を検出し、Vitestを修正版へ更新。最終 `npm audit` は脆弱性0件。
- サンドボックス内では仮想環境のensurepip、一時フォルダへのアクセス、esbuild子プロセスの起動が制限された。依存導入と該当検証は自動承認された通常権限で実行し成功。仮想環境のpipも補完済み。
- 未解決事項：APIテスト時にStarletteがhttpx使用の非推奨警告を1件出すが、テスト・依存整合性チェックは成功。Chromeの手動操作、実行ファイル形式での配布は未検証。画像生成・DB・Chrome自動起動は後続工程の範囲。
- 次工程：03. Chrome自動起動・SSE生存監視・自動終了。

## 01. リポジトリ初期化・AI開発ルール整備（2026-10-10）

- 既存の企画書・工程書・ロードマップ・DDL・AGENTS.mdを確認。AGENTS.local.mdは存在せず、着手時の作業ツリーに変更なし。
- SPEC.md、ARCHITECTURE.md、backend/frontend/tests/scriptsの配置を整備。既存のAI開発ルールとDDLは維持。
- READMEへ現在実行できる資料検証コマンドと工程02以降の実装予定を記載。Python・フロントエンドの生成物、環境変数ファイル、ログを.gitignoreへ追加。
- Python 3.12.4で `python scripts/check_repository.py` を実行し、構成とローカルMarkdownリンクの検証に成功。
- `git diff --check` に成功。
- アプリ本体は未実装のため、API・UIの起動、ビルド、型検査、ユニット・統合テストは対象外。これらの手順・検証は工程02で追加する。
- 環境確認ではPythonを検出。Node.js/npmは現在のPATHで検出できず、工程02の着手時に利用可能な実行環境を確認する。
- 次工程：02. FastAPI＋Reactの最小構成。
