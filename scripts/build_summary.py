# -*- coding: utf-8 -*-
"""全銘柄の「検索結果のまとめ」を1つの CSV にする（docs/summary.csv）。

2026-10-25 ご本人の依頼: 保有している銘柄をGoogleスプレッドシートで一括管理して、各銘柄の
売り時（または買い増し）の目安を見たい。中身は銘柄検索と同じでよい。
→ スプレッドシートが IMPORTDATA でこの CSV を読み、保有銘柄のコードで引く。
   保有銘柄そのものは公開しない（ご本人のスプレッドシートの中だけにある）。
2026-10-26 高配当株 15指標・グロース株をやめ、PER×PBR の幅を足した（列の並びが変わったので、
シートの式も作り直した: 自動トレード\\保有銘柄シート_貼り付け用.txt）。

列（1銘柄1行）:
  1 コード  2 銘柄名  3 株価  4 EPS（直近の通期）  5 BPS（直近の通期）
  6〜8 PERの幅 過去10年の下・中央値・上  9〜11 PERの中央値 過去5・3・1年
  12〜14 PER×PBRの幅 過去10年の下・中央値・上  15〜17 PER×PBRの中央値 過去5・3・1年
  18 連続増配株か  19 連続増配の加点  20 期待値投資（載る／×（外れた条件））
  21 配当利回り  22 配当性向  23 業種  24 株価の日付
幅は銘柄検索と同じ（毎月の値の下から1割・中央値・上から1割）。今のPER・PER×PBRと目安は、
スプレッドシートがその時の株価（GOOGLEFINANCE）と EPS・BPS で出す。

使い方（build_detail.py のあとに実行する）:
    python scripts/build_summary.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
YEARS = (10, 5, 3, 1)


def band(v: pd.Series, years: int):
    p = v.tail(years * 12).dropna()
    if len(p) < min(12, years * 6):
        return None
    return [round(float(np.quantile(p, q)), 1) for q in (0.1, 0.5, 0.9)]


def kitaichi_text(k: dict) -> str:
    """期待値投資に載るか。載らないときは、外れた条件を短く（2026-10-25 ご本人から「全部 – なのはなぜ」）。"""
    if not k:
        return "データなし"
    if k.get("通過"):
        return "載る"
    why = []
    y, pr, sales, op = k["配当利回り"], k["配当性向"], k["売上"], k["営業利益"]
    if not y[1]:
        why.append(f"利回り{y[0]}%")
    if not pr[1]:
        why.append(f"配当性向{pr[0]}%" if pr[0] is not None else "配当性向なし")
    if not sales[1]:
        why.append(f"増収{sales[0]}期連続")
    elif op[1] is False:
        why.append("営業利益が伸びていない")
    elif op[1] is None:
        why.append(f"営業利益が{k.get('営業利益期数', 0)}期分しかなく未確認")
    return "×（" + "・".join(why) + "）"


def build() -> int:
    idx = json.loads((DOCS / "per" / "index.json").read_text(encoding="utf-8"))
    detail = {}
    for f in glob.glob(str(DOCS / "detail" / "*.json")):
        detail.update(json.loads(Path(f).read_text(encoding="utf-8"))["stocks"])
    rows = []
    for code, (name, price) in sorted(idx["stocks"].items()):
        f = DOCS / "per" / f"{code}.csv"
        if not f.exists():
            continue
        m = pd.read_csv(f)
        pp = m["PERxPBR"] if "PERxPBR" in m else pd.Series(dtype=float)
        b = {y: band(m["PER"], y) for y in YEARS}
        c = {y: band(pp, y) for y in YEARS}
        d = detail.get(code, {})
        r, k = d.get("連続増配", {}), d.get("期待値", {})
        mid = lambda x: x[1] if x else None
        rows.append({
            "コード": code, "銘柄名": name, "株価": price, "EPS": m["EPS"].iloc[-1],
            "BPS": m["BPS"].iloc[-1] if "BPS" in m else None,
            "PER下10年": b[10][0] if b[10] else None, "PER中央10年": mid(b[10]), "PER上10年": b[10][2] if b[10] else None,
            "PER中央5年": mid(b[5]), "PER中央3年": mid(b[3]), "PER中央1年": mid(b[1]),
            "PERxPBR下10年": c[10][0] if c[10] else None, "PERxPBR中央10年": mid(c[10]),
            "PERxPBR上10年": c[10][2] if c[10] else None,
            "PERxPBR中央5年": mid(c[5]), "PERxPBR中央3年": mid(c[3]), "PERxPBR中央1年": mid(c[1]),
            "連続増配株": "載る" if r.get("第1段階通過") and r.get("第2段階通過") else "–",
            "連続増配の加点": r.get("合計"),
            "期待値投資": kitaichi_text(k),
            "配当利回り": d.get("配当利回り"), "配当性向": (k.get("配当性向") or [None])[0],
            "業種": d.get("業種"), "株価の日付": idx["asof"],
        })
    out = pd.DataFrame(rows)
    out.to_csv(DOCS / "summary.csv", index=False, encoding="utf-8", lineterminator="\n")
    return len(out)


if __name__ == "__main__":
    n = build()
    print(f"作成: {DOCS / 'summary.csv'}  {n}銘柄")
