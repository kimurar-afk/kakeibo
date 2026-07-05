"""
DBスキーマ定義。

- ローカル/開発時: SQLite(kakeibo.db)
- 本番(Streamlit Cloud等): st.secrets["DATABASE_URL"] にSupabase/NeonのPostgres接続文字列を設定すると
  そちらを使う(再デプロイでもデータが消えない)。

テーブル:
  transactions      : 取引明細(カード明細から取り込んだ支出)
  categories        : カテゴリ一覧(デフォルト+編集可能)
  category_rules    : キーワード -> カテゴリ の仕分けルール
  exclusion_keywords : 集計から除外する行のキーワード(手数料・元本分など)
  incomes           : 月ごとの収入(手入力)
"""

from __future__ import annotations

import os

from sqlalchemy import (
    Column,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    month = Column(String, nullable=False, index=True)  # YYYY-MM
    description = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    category = Column(String, nullable=True)  # NULL = 未分類
    hash = Column(String, unique=True, nullable=False, index=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    sort_order = Column(Integer, default=0)


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)


class ExclusionKeyword(Base):
    __tablename__ = "exclusion_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String, unique=True, nullable=False)


class Income(Base):
    __tablename__ = "incomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, unique=True, nullable=False)  # YYYY-MM
    amount = Column(Integer, nullable=False)
    memo = Column(String, nullable=True)


DEFAULT_CATEGORIES = [
    "食費",
    "日用品",
    "交通費",
    "娯楽",
    "光熱費",
    "通信費",
    "医療費",
    "被服費",
    "特別費",
    "その他",
]

# 「利用内容」に含まれていたら仕分け対象から除外するキーワード
# (実消費ではなく、分割払いの手数料/元本内訳などの内部調整行)
DEFAULT_EXCLUSIONS = [
    "手数料",
    "元本分",
    "調整金額",
    "キャッシング返済",
    "リボ払い元金",
    "口座振替",
    "前回分",
]

# 初期のキーワード辞書(叩き台)。実データを見ながら追加・修正していく前提。
# キーは正規化後(NFKC + upper)の半角文字列で比較する。
DEFAULT_RULES = {
    # 食費
    "コンビニ": "食費",
    "セブンイレブン": "食費",
    "ファミリーマート": "食費",
    "ローソン": "食費",
    "スーパー": "食費",
    "イオン": "食費",
    "マクドナルド": "食費",
    "モスバーガー": "食費",
    "スターバックス": "食費",
    "サイゼリヤ": "食費",
    "吉野家": "食費",
    "すき家": "食費",
    "カフェ": "食費",
    "レストラン": "食費",
    "恵那川上屋": "食費",
    # 日用品
    "アマゾン": "日用品",
    "amazon": "日用品",
    "マーケットプレイス": "日用品",
    "ドラッグ": "日用品",
    "ダイソー": "日用品",
    "無印良品": "日用品",
    "ニトリ": "日用品",
    "楽天": "日用品",
    # 交通費
    "jr": "交通費",
    "suica": "交通費",
    "pasmo": "交通費",
    "タクシー": "交通費",
    "ana": "交通費",
    "jal": "交通費",
    "新幹線": "交通費",
    "メトロ": "交通費",
    "名鉄": "交通費",
    "近鉄": "交通費",
    # 娯楽
    "netflix": "娯楽",
    "spotify": "娯楽",
    "itunes": "娯楽",
    "app store": "娯楽",
    "アソビュー": "娯楽",
    "カラオケ": "娯楽",
    "映画": "娯楽",
    "ディズニー": "娯楽",
    # 光熱費
    "電気": "光熱費",
    "ガス": "光熱費",
    "水道": "光熱費",
    "東京電力": "光熱費",
    "中部電力": "光熱費",
    "東邦ガス": "光熱費",
    # 通信費
    "docomo": "通信費",
    "au ": "通信費",
    "softbank": "通信費",
    "ソフトバンク": "通信費",
    "携帯": "通信費",
    "プロバイダ": "通信費",
    # 医療費
    "クリニック": "医療費",
    "病院": "医療費",
    "薬局": "医療費",
    "歯科": "医療費",
    # 被服費
    "ユニクロ": "被服費",
    "zara": "被服費",
    "gap": "被服費",
    # 特別費
    "高島屋": "特別費",
    "旅行": "特別費",
    "ホテル": "特別費",
}


def get_engine():
    database_url = None
    try:
        import streamlit as st

        database_url = st.secrets.get("DATABASE_URL")
    except Exception:
        pass
    if not database_url:
        database_url = os.environ.get("DATABASE_URL", "sqlite:///kakeibo.db")
    return create_engine(database_url, pool_pre_ping=True)


_engine = None
_SessionLocal = None


def init_db():
    global _engine, _SessionLocal
    _engine = get_engine()
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)

    with _SessionLocal() as session:
        if session.query(Category).count() == 0:
            for i, name in enumerate(DEFAULT_CATEGORIES):
                session.add(Category(name=name, sort_order=i))
        if session.query(ExclusionKeyword).count() == 0:
            for kw in DEFAULT_EXCLUSIONS:
                session.add(ExclusionKeyword(keyword=kw))
        if session.query(CategoryRule).count() == 0:
            for kw, cat in DEFAULT_RULES.items():
                session.add(CategoryRule(keyword=kw, category=cat))
        session.commit()

    return _SessionLocal


def get_session():
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()
