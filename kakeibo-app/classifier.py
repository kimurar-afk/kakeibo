"""
ルールベースの仕分けロジック。

カード明細の「ご利用内容」は全角英数字(例: Ｎｅｔｆｌｉｘ、ＪＲ名古屋高島屋)で
出力されることが多いため、比較前に unicodedata.normalize("NFKC", ...) で
半角化・小文字化して、キーワード辞書とのマッチ精度を上げている。
(片仮名の店名(例: アマゾン)はNFKCでは英字に変換されないため、辞書側にも
 片仮名表記のキーワードを別途登録している)
"""

from __future__ import annotations

import unicodedata


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def is_excluded(description: str, exclusion_keywords: list[str]) -> bool:
    norm_desc = normalize(description)
    for kw in exclusion_keywords:
        if normalize(kw) in norm_desc:
            return True
    return False


def classify(description: str, rules: dict[str, str]) -> str | None:
    """
    rules: {keyword: category} の辞書(keywordは未正規化のままでよい)
    マッチしなければ None(未分類)を返す。
    最初にヒットしたルールを採用する(rulesの挿入順に依存するため、呼び出し側で
    優先度をつけたい場合は辞書の順序を調整する)。
    """
    norm_desc = normalize(description)
    for kw, cat in rules.items():
        if normalize(kw) in norm_desc:
            return cat
    return None


def suggest_keyword(description: str, max_len: int = 8) -> str:
    """
    手動でカテゴリを割り当てた際に、ルール辞書へ登録する候補キーワードを
    説明文から作る。全角スペース(店舗の所在地区切りに使われることが多い)より
    前の部分を使い、それでも長ければ先頭 max_len 文字に切り詰める。
    """
    head = description.split("　")[0].strip()
    if not head:
        head = description.strip()
    return head[:max_len]
