# LoopImageGenerator V2 構成

本書は配置と責務を定める。工程09までのAPI・UI、起動制御、SQLite基盤、参考画像管理、ComfyUI実行・タグ付け基盤とタグ評価の計算処理を実装済み。

## リポジトリ構成

| パス | 責務 |
|---|---|
| `backend/` | Python / FastAPI。ComfyUI連携、タグ集計、保存、起動・終了制御 |
| `frontend/` | React / TypeScript。画像投入、評価、履歴・枝切り替え |
| `tests/` | バックエンド・統合テスト。フロントエンド固有テストは `frontend/` 内に配置 |
| `scripts/` | 開発・検証用スクリプト |
| `sql/schema.sql` | SQLite構造と制約の正本 |
| `documents/` | 企画・工程・進捗・工程ごとの検証記録 |

## 処理境界

React → FastAPI → ComfyUI APIの順に生成を依頼する。FastAPIは生成結果とタグを検証し、完成GenerationをSQLiteへ保存する。生成連携と保存は後続工程で実装する。

工程02では `backend/main.py` が `/api/health` を提供し、ビルド済み `frontend/dist/` を静的配信する。UI未ビルドでもAPIは起動できる。開発時はVite（127.0.0.1:5173）の `/api` プロキシがFastAPI（127.0.0.1:8000）へ接続する。どちらもループバックへ限定して起動する。UIは接続状態を表示し、APIのアクセス・疎通ログはコンソールへ出力する。詳細な起動・検証手順はREADMEを参照。

UIの評価状態はReact内に保持する。評価確定時に親画像IDを送信し、バックエンドは同じ親Generationの画像か、重複・好き嫌いの交差がないかを検証する。

DB接続ごとに外部キーを有効化する。画像枚数の一致など行制約で保証できない条件は保存層で検証する。画像は一時領域で生成・タグ付けし、完成後のファイル配置とDBコミットの失敗を清掃・復旧処理で扱う。これらの実装は工程04・11・15で行う。

`backend/launcher.py` はループバックのAPI待受開始後に、一時プロファイルを使った専用Chromeを起動する。Reactは `/api/events` のEventSource接続を保持し、アンマウント時に閉じる。`backend/lifecycle.py` は接続数を監視し、最後の切断から10秒以内の再接続を許容する。初回接続が30秒以内に来なければ停止する。終了時に専用Chromeを清掃する。開発用の `backend.main:app` では自動起動・自動終了を無効にする。ComfyUI固有のワークフローと出力形状は連携層に閉じ込め、工程07・08で確認する。

## 開発の境界

`backend/tag_feedback.py` は群別のタグ出現率と、前回条件の50%継承を計算する純粋な処理です。符号付き重みからpositive/negative候補を返し、共通タグは維持します。暫定数式はREADMEに記載し、実画像での精緻化は保留します。ComfyUI用プロンプトへの変換、API・UIとの接続、選択画像IDの検証と履歴保存は後続工程で行います。

一度に1工程の範囲を実装し、必要な検証を実行してから [ロードマップ](documents/ROADMAP.md) を更新する。設定・保存場所・配布方式など未確定の詳細を本書だけで確定しない。仕様判断は [企画書](documents/PROJECT_PLAN.md) に従う。

`backend/config.py` はTOML設定の検証と保存パスの解決、`backend/database.py` はDDL初期化・接続・トランザクションを担当する。FastAPI lifespanで初期化し、設定とDBはapp.stateへ保持する。設定ファイルは `config.toml`、保存データの既定配置はGit対象外の `data/`。配布時はDDLと設定ファイルを含める。

`backend/projects.py` はプロジェクト作成・一覧・詳細APIを提供する。SQLはパラメータで値を渡し、世代数は対象プロジェクトだけを集計する。参考画像未登録はDBで空文字、APIでnull。作成時にGenerationは保存しない。Reactは選択中のプロジェクトを一時状態として保持し、切替時に詳細を再取得する。応答が逆順になっても最後の選択を優先する。

`backend/comfyui.py` はAPI形式ワークフローの読み込み・投入・履歴監視・例外分類を担当する。呼び出し側がhttpx.AsyncClientの寿命を管理し、非同期実行とキャンセルに対応する。DBへの書き込みは行わない。`scripts/check_comfyui.py` と `workflows/connection_check*.json` は実機の成功・失敗検証に用いる。タグ結果解釈、画像取得、生成条件変更と完成Generation保存は後続工程で追加する。
