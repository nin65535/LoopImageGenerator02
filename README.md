# LoopImageGenerator V2

**画像を選ぶだけで、次の画像が生まれる。**

LoopImageGenerator V2は、参考画像を起点に、生成結果の「好き」「嫌い」を選びながら画像探索を繰り返すローカルアプリです。ユーザーにプロンプト入力を要求しません。画像生成・タグ付けの実処理はComfyUIのAPIへ委任します。

> **開発状況：工程07・ComfyUI API接続・ワークフロー実行基盤（2026-10-10時点）**
> プロジェクトの作成・一覧・再開、参考画像の投入・保存・表示、ComfyUIワークフロー実行基盤を実装済みです。画像生成・評価は今後の工程で追加します。進捗は [ロードマップ](documents/ROADMAP.md) を参照してください。

## 使い方（予定）

1. 新規プロジェクトを作成し、最初の参考画像を投入します。
2. ComfyUIが画像を自動タグ付けし、設定した枚数の候補を生成します（初期値10枚）。
3. 候補に「好き」「嫌い」を付けます。どちらか合計1枚以上を指定すれば次へ進めます。未評価の画像はそのままで構いません。
4. 選択画像のタグ差分を利用し、前回までの条件を50%引き継ぎながら次の候補を生成します。
5. 満足するまで繰り返します。過去のGenerationへ戻り、別の枝を生成することもできます。

同じ選択から繰り返し生成しても、乱数seedが変わるため異なる結果を探索できます。画像拡大や高解像度仕上げの機能は対象外です。

## 特徴（予定）

- プロンプト不要。参考画像と好き／嫌いの選択を主な入力とする。
- 生成枚数とアスペクト比はコンフィグから変更可能。
- 各画像のタグ情報と生成に使用したパラメータを履歴として保存。
- 世代を木構造で管理し、任意の段階から分岐・再開可能。
- チャットのように生成履歴を下へ追加するデスクトップ向け縦スクロールUI。
- DBには完全に生成・タグ付け済みのGenerationだけを登録。未確定の選択は保存しない。

## システム構成

| レイヤー | 技術 | 役割 |
|---|---|---|
| UI | React / TypeScript + Chrome | 画像一覧、好き／嫌い選択、履歴・分岐表示 |
| API | FastAPI / Python | ComfyUI連携、タグ集計、生成とライフサイクル制御 |
| データベース | SQLite | projects / generations / images |
| 画像生成・タグ付け | ComfyUI API | Stable Diffusionによる生成、WD14Tagger等によるタグ付け |

バックエンド起動時に専用Chromeウィンドウを自動表示し、SSE接続監視を使って最後のUI接続が切れてから10秒後にバックエンドも停止します。再読み込みや瞬断は猶予内の再接続で継続します。想定環境はデスクトップの1920px幅モニタです。

## データモデル

- **Project**: 参考画像から始まる一連の生成履歴。
- **Generation**: 親Generation、親画像の選択結果、実際に使った生成パラメータを持つ完成済みノード。
- **Image**: Generationで出力された画像とseed・タグJSON。各Generationの枚数は設定に従う。

過去のGenerationを書き換えずに新しい子ノードを追加することで、同じ親から複数の経路を残します。

## 開発・起動方法

Python 3.12以上、Node.js 22.12以上（検証環境：Python 3.12.4 / Node.js 26.9.0）、npmを使用します。以下はAIが行うセットアップ・起動・検証の再現手順です。コードの手入力・修正は不要です。

リポジトリルートで依存関係を導入します。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
```

開発時は2つのターミナルで、それぞれAPIとUIを起動します。

```powershell
.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
npm --prefix frontend run dev
```

UIは `http://127.0.0.1:5173`。Viteが `/api` をローカルAPIへ転送するため、画面は相対URLで通信します。APIの疎通確認は `http://127.0.0.1:8000/api/health`。アクセスログと疎通ログはAPIのコンソール、接続失敗の詳細はブラウザのコンソールへ出力します。

配布用UIは次の手順でビルドし、FastAPIから配信します。開発用APIを停止してから起動してください。

```powershell
npm --prefix frontend run build
.venv/Scripts/python -m backend.launcher
```

APIの待受開始後、`http://127.0.0.1:8000` を専用Chromeで自動表示します。起動ごとの一時プロファイルを使い、普段のChromeとは独立して動作します。全UI接続が切れてから10秒で終了し、初回接続が30秒以内に来ない場合も終了します。Chrome未導入・UI未ビルドは起動時にエラーを表示します。ポート変更は `--port 8001` で指定できます。Ctrl+Cでも停止できます。

配信には `backend/`、`sql/schema.sql`、`config.toml` と `frontend/dist/`、Pythonの実行環境と `requirements.txt` の依存が必要です。実行ファイル化などの最終配布方式は保留です。開発用の `uvicorn backend.main:app --reload` はChrome自動起動・自動終了を行いません。

基本検証（リポジトリルート）：

```powershell
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check backend tests scripts/check_browser.py scripts/check_lifecycle.py scripts/check_projects.py
.venv/Scripts/python -m ruff format --check backend tests scripts/check_browser.py scripts/check_lifecycle.py scripts/check_projects.py
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
python scripts/check_repository.py
git diff --check
```

APIテストは疎通・静的配信・プロジェクト作成・入力検証・プロジェクト間の分離・再起動後の永続性を、UIテストはAPI接続・作成・切替・応答順序の逆転・作成失敗を検証します。資料検証スクリプトは構成とローカルMarkdownリンクを検証します。

起動済みのAPI・UIとインストール済みChromeを使ったブラウザ検証：

```powershell
.venv/Scripts/python scripts/check_browser.py
.venv/Scripts/python scripts/check_browser.py --url http://127.0.0.1:5173
```

1つ目はビルド済みUI、2つ目は開発用UIのReact表示とAPI通信を1920pxのヘッドレスChromeで検証します。工程02の検証にComfyUIは不要です。

工程03のChrome自動起動・SSE監視・終了の統合検証（事前のAPI起動は不要）：

```powershell
.venv/Scripts/python -m scripts.check_lifecycle
```

ビルド済みUIとインストール済みChromeを使用し、連続再読み込み、複数タブ、最後のタブ終了、Chrome強制終了後のバックエンド停止をヘッドレスChromeで確認します。検証時のみ終了猶予を1.5秒に短縮します。

ディレクトリの責務は [ARCHITECTURE.md](ARCHITECTURE.md)、仕様概要は [SPEC.md](SPEC.md) に記載しています。ユーザーにコードの手入力・書き換えを要求せず、セットアップと実装・検証はAIが担当します。

## プロジェクトの作成と再開

画面の「新規プロジェクト」で名前を入力し、「作成する」を押します。名前の前後の空白は除去し、1〜200文字を受け付けます。同名でもIDで区別します。「プロジェクトを選んで再開」から保存済みプロジェクトを開けます。アプリを終了してもSQLiteに保持され、次の起動で一覧から選択できます。選択中のプロジェクトは画面内の一時状態で、再読み込み後は選び直します。

APIは `POST /api/projects`（JSON: `{"name":"名前"}`）、`GET /api/projects`、`GET /api/projects/{id}`。詳細には保存済み世代数と参考画像の登録状態を返し、存在しないIDは404、不正入力は422になります。参考画像未登録時はDBの `initial_image_path` を空文字、APIでは `null` として扱います。プロジェクト作成ではGenerationや画像行を作りません。世代表示・枝の再開は工程14で追加します。

プロジェクトを開き、参考画像を1枚ドロップするか「参考画像を選択」で登録します。PNG・JPEG・WebPの静止画像、最大20MiB・2,500万画素に対応します。拡張子や申告された形式に依存せず実際に画像を検証し、保存先の `references/` にランダムな名前で保存します。登録済み画像は再開時にも表示され、上書きはできません。別の参考画像を使う場合は新規プロジェクトを作成してください。

`PUT /api/projects/{id}/initial-image` は画像バイナリを直接受け付けます（multipart形式ではありません）。成功時は更新されたプロジェクトを返します。容量・画素数超過は413、未対応形式・アニメーションは415、破損画像は422、登録済みは409です。`GET /api/projects/{id}/initial-image` で画像を取得できます。登録失敗時はDBをロールバックし、作成したファイルを清掃します。参考画像登録でもGeneration・画像行は作りません。プロセス強制終了時の残骸清掃は工程15の範囲です。

画像選択・ドロップ・破損画像からの再試行・再読み込み・再起動後の表示を実Chromeで検証する手順：

```powershell
.venv/Scripts/python -m scripts.check_reference_images
```

一時DBと1920pxの実Chrome（ヘッドレス）で、作成・切替・再読み込み・APIとChrome終了後の再開を検証できます。実データは変更しません。

```powershell
.venv/Scripts/python -m scripts.check_projects
```

## 設定とSQLite初期化

ルートの `config.toml` でComfyUI URL、保存ディレクトリ、生成枚数、幅・高さ、SSE終了猶予・初回接続待ち時間（秒）を設定します。既定値はURL `http://127.0.0.1:8188`、保存先 `data/`、10枚、512×512、10秒・30秒です。設定変更の反映には再起動が必要です。枚数・寸法・待ち時間は正の整数、URLはHTTP(S)とし、不明なキーや不正値は起動時に拒否します。

`LOOP_IMAGE_CONFIG` 環境変数で別のTOMLファイルを指定できます。相対保存先は設定ファイルの所在を基準に解決します。既定ファイルがない場合は組み込み初期値を使用し、明示指定したファイルがない場合はエラーにします。

API起動時に保存先を作成し、`loop-image-generator.sqlite3` に `sql/schema.sql` の3テーブルを初期化します。再起動時は既存データを保持します。初期化だけ行う場合のAI実行手順：

```powershell
.venv/Scripts/python -c "from backend.config import load_settings; from backend.database import Database; Database(load_settings().database_path).initialize()"
```

`Database.connect()` は毎接続で外部キーを有効化して終了時に閉じ、`Database.transaction()` は成功時コミット・例外時ロールバックを行います。枚数と画像行数の一致、評価IDの整合性、完成Generationの保存とファイル管理は工程11で実装します。既存DBの制約変更を移行する仕組みは未実装です。

## 開発方針

V1は手作業による開発でしたが、V2は**人間による手打ちコード0行**で開発します。人間は要件と完成判定を担当し、ソースコード、設定、SQL、テスト、CI等の作成・修正はAIが行います。開発者向けの詳細指示は [`AGENTS.md`](AGENTS.md) を参照してください。

## 資料・参照先

- V1: https://github.com/nin65535/loop-image-generator
- V2: https://github.com/nin65535/LoopImageGenerator02
- 企画書・DDL・実装ロードマップ・工程書: https://drive.google.com/drive/folders/1lnxWhstGr4h6vCoc9bffuVLM7zmn9OOB

## 非対象・将来課題

- 非対象：画像のアップスケール、仕上げ機能、ユーザーへのプロンプト手入力要求。
- 将来課題：タグ推定確率の取得、評価反映アルゴリズムの精緻化。

## ComfyUIワークフロー実行（工程07）

`backend/comfyui.py` がAPI形式JSONの読み込み、`POST /prompt`、返却されたprompt_idの`GET /history/{prompt_id}`監視を担当します。成功は履歴のcompleted=trueとstatus_str=successで判定し、outputsと履歴全体を返します。HTTPエラー・接続失敗・不正JSON・実行エラー・中断は例外として診断情報と取得済みprompt_idを保持します。タグ解析と生成UIへの接続は後続工程です。

AIによる実機検証手順（起動済みComfyUIをconfig.tomlのURLで使用）：

```powershell
.venv/Scripts/python -m scripts.check_comfyui workflows/connection_check.json --timeout 30
.venv/Scripts/python -m scripts.check_comfyui workflows/connection_check_invalid.json --timeout 30
```

1つ目はモデル不要のEmptyImage→PreviewImageで64×64画像をComfyUIの一時領域に出力し、成功時は終了コード0とprompt_id・outputsを表示します。2つ目は意図的な存在しないノードで失敗し、終了コード1と診断JSONを表示するのが期待結果です。DBや既存プロジェクトは変更しません。

任意のAPI形式ワークフローJSONも同じコマンドで実行できます。エディタ保存形式は拒否します。ComfyUIがサーバー側でノード・入力の妥当性を検証します。ワークフロー固有のモデルやカスタムノードは実行先に必要です。[公式APIサンプル](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py)と[公式サーバー実装](https://github.com/Comfy-Org/ComfyUI/blob/master/server.py)を参照して実装しています。

待機上限は投入を含め既定300秒、履歴確認間隔は0.5秒、各HTTP要求は最大30秒です。通信失敗時の自動再投入は行いません。タイムアウトや呼び出し側のキャンセルで待機を終えてもComfyUI側の実行は継続する可能性があります。投入応答を受け取れなかった場合はprompt_idが不明になるため、ComfyUI側のキューを確認してから再実行します。診断出力にはワークフロー由来の情報が含まれる場合があります。
