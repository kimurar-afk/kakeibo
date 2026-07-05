"""
家計簿アプリ(カード明細エクセルを自動仕分け・月次収支可視化)

構成:
  - パスワード認証(st.secrets["APP_PASSWORD"])
  - ① 明細アップロード: エクセルを読み込み、除外行を弾いてルールベースで仕分け、DBに保存(重複は自動スキップ)
  - ② 取引一覧・仕分け修正: 月ごとの取引を一覧表示し、カテゴリをその場で修正(修正内容はルール辞書に自動反映)
  - ③ 月次サマリー: カテゴリ別円グラフ、収支サマリー、直近の支出推移
  - ④ 収入入力: 月ごとの収入を手入力
  - ⑤ カテゴリ・ルール管理: カテゴリ/仕分けルール/除外キーワードの追加・編集・削除

実行:
  streamlit run app.py
"""

from __future__ import annotations

import os
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from classifier import classify, is_excluded, suggest_keyword
from db import (
    Category,
    CategoryRule,
    ExclusionKeyword,
    Income,
    Transaction,
    init_db,
)
from parser import ParseError, parse_excel

# 日本語フォント(環境にあれば使う。無ければ文字化けするがグラフ自体は表示される)
plt.rcParams["axes.unicode_minus"] = False
for font_name in ["IPAexGothic", "Hiragino Sans", "Noto Sans CJK JP", "Yu Gothic"]:
    try:
        plt.rcParams["font.family"] = font_name
        break
    except Exception:
        continue

st.set_page_config(page_title="家計簿アプリ", page_icon="💰", layout="wide")


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------
def check_password() -> bool:
    correct = st.secrets.get("APP_PASSWORD") if hasattr(st, "secrets") else None
    if not correct:
        correct = os.environ.get("APP_PASSWORD", "changeme")

    if st.session_state.get("authed"):
        return True

    st.title("💰 家計簿アプリ")
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        if pw == correct:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False


# ---------------------------------------------------------------------------
# DB初期化(セッションキャッシュ)
# ---------------------------------------------------------------------------
@st.cache_resource
def _init():
    return init_db()


def get_session():
    SessionLocal = _init()
    return SessionLocal()


def load_categories(session) -> list[str]:
    rows = session.query(Category).order_by(Category.sort_order).all()
    return [r.name for r in rows]


def load_rules(session) -> dict[str, str]:
    rows = session.query(CategoryRule).order_by(CategoryRule.id).all()
    return {r.keyword: r.category for r in rows}


def load_exclusions(session) -> list[str]:
    rows = session.query(ExclusionKeyword).all()
    return [r.keyword for r in rows]


def upsert_rule(session, keyword: str, category: str):
    existing = session.query(CategoryRule).filter_by(keyword=keyword).first()
    if existing:
        existing.category = category
    else:
        session.add(CategoryRule(keyword=keyword, category=category))
    session.commit()


# ---------------------------------------------------------------------------
# ① 明細アップロード
# ---------------------------------------------------------------------------
def page_upload(session):
    st.header("① 明細アップロード")
    st.write("カード会社の利用明細エクセル(現状はアメックス系「ご利用履歴」形式)をアップロードしてください。")

    uploaded = st.file_uploader("エクセルファイル", type=["xlsx"])
    if uploaded is None:
        return

    try:
        txs = parse_excel(uploaded)
    except ParseError as e:
        st.error(f"読み込みエラー: {e}")
        return

    exclusions = load_exclusions(session)
    rules = load_rules(session)

    existing_hashes = {h for (h,) in session.query(Transaction.hash).all()}

    new_rows = []
    excluded_count = 0
    dup_count = 0
    for t in txs:
        if is_excluded(t.description, exclusions):
            excluded_count += 1
            continue
        if t.hash in existing_hashes:
            dup_count += 1
            continue
        cat = classify(t.description, rules)
        new_rows.append(
            {
                "date": t.date,
                "month": t.date[:7],
                "description": t.description,
                "amount": t.amount,
                "category": cat,
                "hash": t.hash,
            }
        )

    st.write(
        f"読み込み件数: {len(txs)} / 除外: {excluded_count}件 / 重複(既に取込済み): {dup_count}件 / "
        f"新規取込対象: {len(new_rows)}件(うち未分類 {sum(1 for r in new_rows if r['category'] is None)}件)"
    )

    if new_rows:
        preview_df = pd.DataFrame(new_rows)
        st.dataframe(preview_df, use_container_width=True)

        if st.button("この内容でDBに取り込む", type="primary"):
            for r in new_rows:
                session.add(Transaction(**r))
            session.commit()
            st.success(f"{len(new_rows)}件を取り込みました。「②取引一覧・仕分け修正」で未分類を確認してください。")
    else:
        st.info("新規に取り込める行はありませんでした(すべて除外または取込済み)。")


# ---------------------------------------------------------------------------
# ② 取引一覧・仕分け修正
# ---------------------------------------------------------------------------
def page_review(session):
    st.header("② 取引一覧・仕分け修正")

    months = [m for (m,) in session.query(Transaction.month).distinct().order_by(Transaction.month.desc()).all()]
    if not months:
        st.info("まだ取引データがありません。「①明細アップロード」から取り込んでください。")
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        selected_month = st.selectbox("対象月", months)
    with col2:
        only_unclassified = st.checkbox("未分類のみ表示", value=False)

    categories = load_categories(session)

    query = session.query(Transaction).filter(Transaction.month == selected_month)
    if only_unclassified:
        query = query.filter(Transaction.category.is_(None))
    rows = query.order_by(Transaction.date.desc()).all()

    if not rows:
        st.info("該当する取引がありません。")
        return

    df = pd.DataFrame(
        [{"id": r.id, "日付": r.date, "内容": r.description, "金額": r.amount, "カテゴリ": r.category or "未分類"} for r in rows]
    )

    edited = st.data_editor(
        df,
        column_config={
            "id": None,  # 非表示
            "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=categories + ["未分類"]),
        },
        disabled=["日付", "内容", "金額"],
        hide_index=True,
        use_container_width=True,
        key=f"editor_{selected_month}_{only_unclassified}",
    )

    if st.button("修正を保存", type="primary"):
        changed = 0
        for _, row in edited.iterrows():
            tx = session.get(Transaction, int(row["id"]))
            new_cat = None if row["カテゴリ"] == "未分類" else row["カテゴリ"]
            if tx.category != new_cat:
                tx.category = new_cat
                changed += 1
                if new_cat is not None:
                    kw = suggest_keyword(tx.description)
                    upsert_rule(session, kw, new_cat)
        session.commit()
        st.success(f"{changed}件のカテゴリを更新しました。新しいルールを仕分け辞書に反映しました。")
        st.rerun()


# ---------------------------------------------------------------------------
# ③ 月次サマリー
# ---------------------------------------------------------------------------
def page_summary(session):
    st.header("③ 月次サマリー")

    months = [m for (m,) in session.query(Transaction.month).distinct().order_by(Transaction.month.desc()).all()]
    if not months:
        st.info("まだ取引データがありません。")
        return

    selected_month = st.selectbox("対象月", months, key="summary_month")

    rows = session.query(Transaction).filter(
        Transaction.month == selected_month, Transaction.category.isnot(None)
    ).all()
    unclassified_count = session.query(Transaction).filter(
        Transaction.month == selected_month, Transaction.category.is_(None)
    ).count()

    total_expense = sum(r.amount for r in rows if r.amount > 0) - sum(-r.amount for r in rows if r.amount < 0)

    income_row = session.query(Income).filter_by(month=selected_month).first()
    income = income_row.amount if income_row else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("収入", f"¥{income:,}")
    c2.metric("支出(分類済み合計)", f"¥{total_expense:,}")
    c3.metric("収支", f"¥{income - total_expense:,}")

    if unclassified_count:
        st.warning(f"未分類の取引が {unclassified_count}件あります。「②取引一覧・仕分け修正」で分類すると集計に反映されます。")

    cat_totals: dict[str, int] = {}
    for r in rows:
        cat_totals[r.category] = cat_totals.get(r.category, 0) + r.amount
    cat_totals = {k: v for k, v in cat_totals.items() if v > 0}

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("カテゴリ別支出")
        if cat_totals:
            fig, ax = plt.subplots()
            ax.pie(cat_totals.values(), labels=cat_totals.keys(), autopct="%1.1f%%")
            ax.axis("equal")
            st.pyplot(fig)
        else:
            st.info("表示できるデータがありません。")

    with col2:
        st.subheader("直近6ヶ月の支出推移")
        all_rows = session.query(Transaction).filter(Transaction.category.isnot(None)).all()
        trend: dict[str, int] = {}
        for r in all_rows:
            if r.amount > 0:
                trend[r.month] = trend.get(r.month, 0) + r.amount
        trend_df = pd.Series(trend).sort_index().tail(6)
        if not trend_df.empty:
            fig2, ax2 = plt.subplots()
            ax2.bar(trend_df.index, trend_df.values)
            ax2.set_ylabel("支出額(円)")
            plt.xticks(rotation=45)
            st.pyplot(fig2)
        else:
            st.info("表示できるデータがありません。")


# ---------------------------------------------------------------------------
# ④ 収入入力
# ---------------------------------------------------------------------------
def page_income(session):
    st.header("④ 収入入力")

    default_month = datetime.now().strftime("%Y-%m")
    month = st.text_input("対象月(YYYY-MM)", value=default_month)
    existing = session.query(Income).filter_by(month=month).first()

    amount = st.number_input("収入額", min_value=0, step=1000, value=existing.amount if existing else 0)
    memo = st.text_input("メモ", value=existing.memo if existing and existing.memo else "")

    if st.button("保存", type="primary"):
        if existing:
            existing.amount = int(amount)
            existing.memo = memo
        else:
            session.add(Income(month=month, amount=int(amount), memo=memo))
        session.commit()
        st.success(f"{month} の収入を保存しました。")

    st.divider()
    st.subheader("登録済みの収入一覧")
    rows = session.query(Income).order_by(Income.month.desc()).all()
    if rows:
        st.dataframe(
            pd.DataFrame([{"月": r.month, "収入": r.amount, "メモ": r.memo} for r in rows]),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# ⑤ カテゴリ・ルール管理
# ---------------------------------------------------------------------------
def page_rules(session):
    st.header("⑤ カテゴリ・ルール管理")

    tab1, tab2, tab3 = st.tabs(["カテゴリ", "仕分けルール", "除外キーワード"])

    with tab1:
        cats = session.query(Category).order_by(Category.sort_order).all()
        st.dataframe(pd.DataFrame([{"カテゴリ名": c.name} for c in cats]), hide_index=True, use_container_width=True)
        new_cat = st.text_input("新しいカテゴリ名")
        if st.button("カテゴリを追加"):
            if new_cat and not session.query(Category).filter_by(name=new_cat).first():
                max_order = session.query(Category).count()
                session.add(Category(name=new_cat, sort_order=max_order))
                session.commit()
                st.success(f"「{new_cat}」を追加しました。")
                st.rerun()

    with tab2:
        rules = session.query(CategoryRule).order_by(CategoryRule.category, CategoryRule.keyword).all()
        categories = load_categories(session)
        rules_df = pd.DataFrame([{"id": r.id, "キーワード": r.keyword, "カテゴリ": r.category} for r in rules])
        edited = st.data_editor(
            rules_df,
            column_config={
                "id": None,
                "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=categories),
            },
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="rules_editor",
        )
        if st.button("ルールを保存", key="save_rules"):
            existing_ids = set(rules_df["id"].tolist())
            edited_ids = set(edited["id"].dropna().tolist()) if "id" in edited else set()
            for rid in existing_ids - edited_ids:
                obj = session.get(CategoryRule, int(rid))
                if obj:
                    session.delete(obj)
            for _, row in edited.iterrows():
                if pd.isna(row.get("id")):
                    if row["キーワード"] and row["カテゴリ"]:
                        upsert_rule(session, row["キーワード"], row["カテゴリ"])
                else:
                    obj = session.get(CategoryRule, int(row["id"]))
                    if obj:
                        obj.keyword = row["キーワード"]
                        obj.category = row["カテゴリ"]
            session.commit()
            st.success("ルールを保存しました。")
            st.rerun()

    with tab3:
        exs = session.query(ExclusionKeyword).all()
        ex_df = pd.DataFrame([{"id": e.id, "除外キーワード": e.keyword} for e in exs])
        edited_ex = st.data_editor(
            ex_df,
            column_config={"id": None},
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="exclusions_editor",
        )
        if st.button("除外キーワードを保存"):
            existing_ids = set(ex_df["id"].tolist())
            edited_ids = set(edited_ex["id"].dropna().tolist()) if "id" in edited_ex else set()
            for eid in existing_ids - edited_ids:
                obj = session.get(ExclusionKeyword, int(eid))
                if obj:
                    session.delete(obj)
            for _, row in edited_ex.iterrows():
                if pd.isna(row.get("id")) and row["除外キーワード"]:
                    if not session.query(ExclusionKeyword).filter_by(keyword=row["除外キーワード"]).first():
                        session.add(ExclusionKeyword(keyword=row["除外キーワード"]))
            session.commit()
            st.success("除外キーワードを保存しました。")
            st.rerun()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    if not check_password():
        return

    st.sidebar.title("💰 家計簿アプリ")
    page = st.sidebar.radio(
        "メニュー",
        ["① 明細アップロード", "② 取引一覧・仕分け修正", "③ 月次サマリー", "④ 収入入力", "⑤ カテゴリ・ルール管理"],
    )

    session = get_session()
    try:
        if page == "① 明細アップロード":
            page_upload(session)
        elif page == "② 取引一覧・仕分け修正":
            page_review(session)
        elif page == "③ 月次サマリー":
            page_summary(session)
        elif page == "④ 収入入力":
            page_income(session)
        elif page == "⑤ カテゴリ・ルール管理":
            page_rules(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
