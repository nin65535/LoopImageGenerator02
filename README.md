# LoopImageGenerator V2

**画像を選ぶだけで、次の画像が生まれる。**

参考画像を起点に、生成結果の「好き」「嫌い」を選びながら画像探索を繰り返すローカルアプリです。プロンプト入力は不要。画像生成・タグ付けにはComfyUIを使い、履歴をSQLiteに保存します。

## 使い方

1. 「新規プロジェクト」で名前・モデル・画像サイズを選びます。
2. 参考画像を登録し、「参考画像から候補を生成」を押します。
3. 候補に「好き」「嫌い」を付けます。合計1枚以上の評価で次へ進めます。
4. 「評価を確定して次世代を生成」を押し、探索を繰り返します。

過去世代からの分岐、枝の切替、保存済みプロジェクトの再開に対応します。「好き」の画像は次世代にも引き継がれ、再評価できます。生成中は進捗と経過時間を表示します。

参考画像はPNG・JPEG・WebPの静止画像（最大20MiB・2,500万画素）に対応します。別の参考画像を使う場合は新規プロジェクトを作成してください。プロジェクトの削除は取り消せません。

## セットアップ・起動

Python 3.12以上、Node.js 22.12以上、npm、Chrome、起動済みのComfyUIが必要です。ComfyUIには使用するモデルと `WD14Tagger|pysssss` を導入します。セットアップ・設定変更はAIが担当します。

リポジトリルートで依存関係を導入し、UIをビルドして起動します。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/Scripts/python -m backend.launcher
```

`http://127.0.0.1:8000` を専用Chromeで自動表示します。すべてのUI接続が切れてから5秒後にバックエンドも終了します。

開発時はAPIとUIを別々のターミナルで起動します。

```powershell
.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
npm --prefix frontend run dev
```

開発用UIは `http://127.0.0.1:5173`。この起動方法ではChromeの自動起動・自動終了は行いません。

## 設定

- [config.toml](config.toml)：ComfyUIのURL、保存先、生成枚数など。変更後は再起動します。既定は `http://127.0.0.1:8188`、`data/`、新規10枚（最低6枚）です。
- 画面右上の歯車：許可モデルと追加画像サイズを管理します。
- プロジェクト作成時：モデルと画像サイズを選び、次世代・分岐でも引き継ぎます。固定サイズは1024×1024・768×1344・1344×768です。

## 基本検証

```powershell
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check backend tests scripts
.venv/Scripts/python -m ruff format --check backend tests scripts
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
python scripts/check_repository.py
git diff --check
```

## 関連資料

- [仕様概要](SPEC.md)
- [システム構成](ARCHITECTURE.md)
- [企画書](documents/PROJECT_PLAN.md)
- [受入確認表](documents/ACCEPTANCE.md)
- [AI開発ルール](AGENTS.md)：人間の手打ちコード0行で開発します。
