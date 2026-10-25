# -*- coding: utf-8 -*-
"""全銘柄の「検索結果のまとめ」を1つの CSV にする（docs/summary.csv）。

2026-10-25 ご本人の依頼: 保有している銘柄をGoogleスプレッドシートで一括管理して、各銘柄の
売り時（または買い増し）の目安を見たい。中身は銘柄検索と同じでよい。
→ スプレッドシートが IMPORTDATA でこの CSV を読み、保有銘柄のコードで引く。
   保有銘柄そのものは公開しない（ご本人のスプレッドシートの中だけにある）。

列（1銘柄1行）:
  コード, 銘柄名, 株価, EPS（直近の通期）, PERの幅 過去10年の下・中央値・上, 過去5・3・1年の中央値,
  15指標の合格, 15指標の対象か, グロース株か, PEG, 連続増配株か, 連続増配の加点,
  期待値投資（載る／×（外れた条件））,
  配当利回り, 配当性向, PBR, 業種, 株価の日付
PERの幅は銘柄検索と同じ（毎月のPERの下から1割・中央値・上から1割）。今のPERと目安は、
スプレッドシートがその時の株価（GOOGLEFINANCE）÷ EPS で出す。

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


def band(per: pd.Series, years: int):
    p = per.tail(years * 12).dropna()
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
        b = {y: band(m["PER"], y) for y in YEARS}
        d = detail.get(code, {})
        hd, g, r, k = d.get("高配当", {}), d.get("グロース", {}), d.get("連続増配", {}), d.get("期待値", {})
        peg = g.get("PEG")
        rows.append({
            "コード": code, "銘柄名": name, "株価": price, "EPS": m["EPS"].iloc[-1],
            "PER下10年": b[10][0] if b[10] else None, "PER中央10年": b[10][1] if b[10] else None,
            "PER上10年": b[10][2] if b[10] else None,
            "PER中央5年": b[5][1] if b[5] else None, "PER中央3年": b[3][1] if b[3] else None,
            "PER中央1年": b[1][1] if b[1] else None,
            # 「9/10」だとスプレッドシートが日付（9月10日）と読むので、全角の／にする（2026-10-25）
            "15指標": f"{hd['合格'][0]}／{hd['合格'][1]}" if hd.get("合格") else None,
            "15指標の対象": "対象" if hd.get("対象") else "対象外",
            "グロース株": "載る" if g.get("対象") and g.get("グロース") else "–",
            "PEG": (f"{peg[0]}（要確認）" if isinstance(peg, list) else peg),
            "連続増配株": "載る" if r.get("第1段階通過") and r.get("第2段階通過") else "–",
            "連続増配の加点": r.get("合計"),
            "期待値投資": kitaichi_text(k),
            "配当利回り": hd.get("配当利回り"), "配当性向": (k.get("配当性向") or [None])[0],
            "PBR": g.get("PBR"), "業種": d.get("業種"), "株価の日付": idx["asof"],
        })
    out = pd.DataFrame(rows)
    out.to_csv(DOCS / "summary.csv", index=False, encoding="utf-8", lineterminator="\n")
    return len(out)


if __name__ == "__main__":
    n = build()
    print(f"作成: {DOCS / 'summary.csv'}  {n}銘柄")
