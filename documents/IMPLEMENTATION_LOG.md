# 工程別の作業・検証記録

## 01. リポジトリ初期化・AI開発ルール整備（2026-10-10）

- 既存の企画書・工程書・ロードマップ・DDL・AGENTS.mdを確認。AGENTS.local.mdは存在せず、着手時の作業ツリーに変更なし。
- SPEC.md、ARCHITECTURE.md、backend/frontend/tests/scriptsの配置を整備。既存のAI開発ルールとDDLは維持。
- READMEへ現在実行できる資料検証コマンドと工程02以降の実装予定を記載。Python・フロントエンドの生成物、環境変数ファイル、ログを.gitignoreへ追加。
- Python 3.12.4で `python scripts/check_repository.py` を実行し、構成とローカルMarkdownリンクの検証に成功。
- `git diff --check` に成功。
- アプリ本体は未実装のため、API・UIの起動、ビルド、型検査、ユニット・統合テストは対象外。これらの手順・検証は工程02で追加する。
- 環境確認ではPythonを検出。Node.js/npmは現在のPATHで検出できず、工程02の着手時に利用可能な実行環境を確認する。
- 次工程：02. FastAPI＋Reactの最小構成。
