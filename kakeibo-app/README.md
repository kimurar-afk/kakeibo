# 家計簿アプリ

カード利用明細のエクセルをアップロードすると、自動で支出を仕分けし、月の収支を可視化するアプリです。

## 構成

- `app.py` : Streamlit画面本体
- `db.py` : DBスキーマ(SQLAlchemy)、デフォルトカテゴリ/仕分けルール/除外キーワード
- `parser.py` : カード明細エクセルの読み込み(現状はアメックス系「ご利用履歴」形式に対応)
- `classifier.py` : ルールベースの仕分けロジック(全角→半角正規化を含む)
- `requirements.txt` : 依存パッケージ

## 主な機能

1. **明細アップロード**: エクセルをアップロード。分割払いの手数料・元本内訳などの非消費行は自動除外。仕分けルールに合致した行は自動でカテゴリ分類、合致しない行は「未分類」として取り込み。同じ取引(日付+内容+金額)は重複取込されません。
2. **取引一覧・仕分け修正**: 月ごとに一覧表示し、カテゴリをその場で修正可能。修正すると「店名(の先頭部分)→カテゴリ」のルールが仕分け辞書に自動登録され、次回以降は自動で分類されます。
3. **月次サマリー**: カテゴリ別支出の円グラフ、当月の収入・支出・収支、直近6ヶ月の支出推移。
4. **収入入力**: 月ごとの収入を手入力(給与などは自動連携せず手入力の想定)。
5. **カテゴリ・ルール管理**: カテゴリの追加、仕分けルール(キーワード↔カテゴリ)の追加・編集・削除、除外キーワードの管理。

## ローカルでの動作確認

```bash
pip install -r requirements.txt
streamlit run app.py
```

ローカル実行時、`.streamlit/secrets.toml` が無ければ以下のデフォルトで動きます。

- パスワード: `changeme`(環境変数 `APP_PASSWORD` で上書き可)
- DB: カレントディレクトリの `kakeibo.db`(SQLite)

## 本番デプロイ手順(Streamlit Community Cloud + Supabase/Neon)

無料PaaSはファイルシステムが一時的なため、SQLiteのままだと再デプロイ時にデータが消えます。
そのため本番では外部の無料PostgreSQL(Supabase または Neon)に接続します。

### 1. Supabase または Neon で無料DBを作成

- [Supabase](https://supabase.com) または [Neon](https://neon.tech) にサインアップし、無料プランでプロジェクトを作成
- 接続文字列(`postgresql://user:password@host:5432/dbname` の形式)を控える
  - Supabaseの場合は Project Settings → Database → Connection string
  - Neonの場合は Dashboard → Connection Details

### 2. GitHubにこのフォルダをpush

`app.py` `db.py` `parser.py` `classifier.py` `requirements.txt` を含むリポジトリを作成してpushします。
(`kakeibo.db` や `.streamlit/secrets.toml` は含めないでください)

### 3. Streamlit Community Cloudでデプロイ

- [share.streamlit.io](https://share.streamlit.io) でリポジトリを選択し、`app.py` を指定してデプロイ
- アプリの Settings → Secrets に以下を貼り付け(`.streamlit/secrets.toml.example` を参考に)

```toml
APP_PASSWORD = "好きなパスワード"
DATABASE_URL = "postgresql://user:password@host:5432/dbname"
```

これでURLからアクセスでき、データはSupabase/Neon側に永続化されます。

## 対応カード明細フォーマットの追加

現状 `parser.py` はヘッダー行の先頭セルが「ご利用日」であるシート(アメックス系)を前提にしています。
他社のカードにも対応させたい場合は、`TRANSACTION_SHEET_CANDIDATES` や `REQUIRED_COLUMNS`、列名の対応関係を
そのフォーマットに合わせて調整してください。実際の明細ファイルを見せてもらえれば、そのフォーマット用の
パーサーを追加できます。
