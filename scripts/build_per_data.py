# -*- coding: utf-8 -*-
"""銘柄ごとの過去10年のPERを、Googleスプレッドシートから読める CSV にして公開する（docs/per/コード.csv）。

2026-10-18 ご本人の依頼: 期待値投資のページの「PERの変化」を、スプレッドシートでも
銘柄コードを入れて調べられるようにしたい。スプレッドシートは IMPORTDATA でこの CSV を読み、
今の株価は GOOGLEFINANCE で取って、今のPERをその場で計算する。

PER の作り方は期待値投資のページと同じ:
  毎月の PER ＝ 月末の株価 ÷ その時点で発表済みの直近の通期EPS（発表は期末の約3か月後として扱う）
  EPS は有価証券報告書（EDINET）の10期分を、株式分割を今の基準に直したもの
  EPS が赤字の月は PER を空欄にする

CSV の列: 年月, 株価, EPS, PER（過去10年分、古い順。今月は月末前なので入れない）
対象: 決算書のある全銘柄（初回は報告書の取得に時間がかかる。以降は新しい報告書だけ取る）

使い方:
    python scripts/build_per_data.py            全銘柄
    python scripts/build_per_data.py 7203 8058  指定した銘柄だけ（試すとき）
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load  # noqa: E402
from build_renzoku import actions_for, adjust  # noqa: E402
from build_kitaichi import fy_ends, monthly_prices  # noqa: E402
import fetch_edinet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "per"


def series(close: pd.Series, a: dict) -> pd.DataFrame:
    known_at = [(pd.Timestamp(fy + "-01") + pd.offsets.MonthEnd(0) + pd.DateOffset(months=3)) for fy in a["fy"]]
    eps = pd.Series(a["EPS"], index=known_at).sort_index()
    eps = eps[~eps.index.duplicated(keep="last")]
    known = eps.reindex(close.index.union(eps.index)).ffill().reindex(close.index)
    df = pd.DataFrame({"株価": close, "EPS": known}).dropna()
    df = df[df.index >= close.index[-1] - pd.DateOffset(years=10)]
    # 今月はまだ月末になっていないので入れない（入れると更新のたびに全銘柄のファイルが変わる）。
    # 今のPERは、検索欄が index.json の最新の株価から出す
    df = df[df.index.to_period("M") < pd.Timestamp.today().to_period("M")]
    df["PER"] = (df["株価"] / df["EPS"]).where(df["EPS"] > 0)
    df.index = df.index.strftime("%Y-%m")
    df.index.name = "年月"
    return df


def build(codes=None) -> int:
    df, _ = load()
    ends = fy_ends()
    names = set(df["code"])
    codes = codes or [c for c in ends.index if c in names]
    print(f"PERの履歴を作る銘柄 {len(codes)}", flush=True)
    raw = fetch_edinet.ten_years({c: ends[c] for c in codes})
    act = actions_for(list(raw), max_age=30)
    px = monthly_prices(list(raw))
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    skipped = 0
    for c, rec in raw.items():
        try:                                   # 1銘柄のデータの不具合で全体が止まらないように
            a = adjust(rec, act.get(c, {}))
            if not a or c not in px or len(px[c]) < 12:
                continue
            s = series(px[c], a)
        except Exception as e:
            skipped += 1
            print(f"  [!] {c} を飛ばしました（{type(e).__name__}）", flush=True)
            continue
        if s.empty:
            continue
        s.round({"株価": 1, "EPS": 2, "PER": 1}).to_csv(OUT / f"{c}.csv", encoding="utf-8", lineterminator="\n")
        n += 1
    print(f"作成: {OUT}  {n}銘柄", flush=True)
    return n


if __name__ == "__main__":
    build(sys.argv[1:] or None)
