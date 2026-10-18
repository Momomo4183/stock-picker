# -*- coding: utf-8 -*-
"""PER検索（トップページの検索欄）が読む銘柄一覧（docs/per/index.json）を作る。

2026-10-18 ご本人の依頼: 銘柄コードを入れると、その銘柄の過去のPERの変化と今のPERが分かる
検索用のページ（スプレッドシートが難しければ銘柄ピックアップのページで）→ トップに検索欄を置いた
（検索欄の HTML・JS は build_top.py の SEARCH_*）。
銘柄ごとのPERは build_per_data.py が docs/per/コード.csv に作る。検索欄はそれを読んで、
期待値投資のページと同じ物差し（過去10年の毎月のPERの下から1割〜上から1割、中央値）で表示する。
今のPERは、ページを作ったときの株価 ÷ 直近の通期EPS。

使い方（build_per_data.py のあとに実行する）:
    python scripts/build_per_page.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def build() -> int:
    df, asof = load()
    have = {p.stem for p in (DOCS / "per").glob("*.csv")}
    d = df[df["code"].isin(have)]
    idx = {r["code"]: [r["name"], round(float(r["株価"]), 1)] for _, r in d.iterrows()}
    (DOCS / "per" / "index.json").write_text(json.dumps({"asof": asof["株価"], "stocks": idx}, ensure_ascii=False),
                                             encoding="utf-8")
    return len(idx)


if __name__ == "__main__":
    n = build()
    print(f"作成: {DOCS / 'per' / 'index.json'}  {n}銘柄")
