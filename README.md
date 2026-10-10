# LoopImageGenerator V2

**画像を選ぶだけで、次の画像が生まれる。**

LoopImageGenerator V2は、参考画像を起点に、生成結果の「好き」「嫌い」を選びながら画像探索を繰り返すローカルアプリです。ユーザーにプロンプト入力を要求しません。画像生成・タグ付けの実処理はComfyUIのAPIへ委任します。

> **開発状況：工程02・FastAPI＋Reactの最小構成（2026-10-10時点）**
> API接続確認画面を実装済みです。画像生成・評価・保存は今後の工程で追加します。進捗は [ロードマップ](documents/ROADMAP.md) を参照してください。

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

バックエンド起動時にChromeを自動表示し、SSE接続監視を使ってブラウザ終了後にバックエンドも停止する構成を予定しています。想定環境はデスクトップの1920px幅モニタとChromeフルスクリーンです。

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
.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000` をChromeで開くと、React画面とAPIを同じ接続先から利用できます。配信には `backend/` と `frontend/dist/`、Pythonの実行環境と `requirements.txt` の依存が必要です。実行ファイル化などの最終配布方式は保留です。Chrome自動起動・終了監視は工程03で実装します。

基本検証（リポジトリルート）：

```powershell
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check backend tests scripts/check_browser.py
.venv/Scripts/python -m ruff format --check backend tests scripts/check_browser.py
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
python scripts/check_repository.py
git diff --check
```

APIテストは疎通・静的配信・未知パスの404を、UIテストはAPI接続の成功・失敗表示を検証します。資料検証スクリプトは構成とローカルMarkdownリンクを検証します。

起動済みのAPI・UIとインストール済みChromeを使ったブラウザ検証：

```powershell
.venv/Scripts/python scripts/check_browser.py
.venv/Scripts/python scripts/check_browser.py --url http://127.0.0.1:5173
```

1つ目はビルド済みUI、2つ目は開発用UIのReact表示とAPI通信を1920pxのヘッドレスChromeで検証します。工程02の検証にComfyUIは不要です。

ディレクトリの責務は [ARCHITECTURE.md](ARCHITECTURE.md)、仕様概要は [SPEC.md](SPEC.md) に記載しています。ユーザーにコードの手入力・書き換えを要求せず、セットアップと実装・検証はAIが担当します。

## 開発方針

V1は手作業による開発でしたが、V2は**人間による手打ちコード0行**で開発します。人間は要件と完成判定を担当し、ソースコード、設定、SQL、テスト、CI等の作成・修正はAIが行います。開発者向けの詳細指示は [`AGENTS.md`](AGENTS.md) を参照してください。

## 資料・参照先

- V1: https://github.com/nin65535/loop-image-generator
- V2: https://github.com/nin65535/LoopImageGenerator02
- 企画書・DDL・実装ロードマップ・工程書: https://drive.google.com/drive/folders/1lnxWhstGr4h6vCoc9bffuVLM7zmn9OOB

## 非対象・将来課題

- 非対象：画像のアップスケール、仕上げ機能、ユーザーへのプロンプト手入力要求。
- 将来課題：タグ推定確率の取得、評価反映アルゴリズムの精緻化。
