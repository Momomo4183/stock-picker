# -*- coding: utf-8 -*-
"""過去の配当と株式分割の履歴を一括で取ってくる（検証用・1回動かせばよい）。

**配当** は①②の条件（配当利回り）に必要。株価と違い、一括ダウンロードで
14年分まとめて取れる。

**株式分割** はリターンの計算に必要。手元の価格データは分割調整されていない
ため、1:2の分割があると株価が半分になり「−50%の暴落」に見えてしまう。
分割比率を掛け戻して連続した株価に直すために使う。

出力:
    data/backtest/dividends.csv   code, 権利落ち日, 配当
    data/backtest/splits.csv      code, 分割日, 分割比率

使い方:
    python backtest/fetch_actions.py
"""
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "backtest"
START, END = "2011-01-01", "2026-09-01"
CHUNK = 200


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = pd.read_csv(ROOT / "stocks.csv", dtype={"code": str},
                        encoding="utf-8-sig")["code"].tolist()
    print(f"対象 {len(codes)}銘柄", flush=True)

    t0, divs, splits = time.time(), [], []
    for i in range(0, len(codes), CHUNK):
        chunk = codes[i:i + CHUNK]
        try:
            d = yf.download([f"{c}.T" for c in chunk], start=START, end=END,
                            interval="1d", group_by="ticker", actions=True,
                            auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print(f"  {i}〜 取得失敗: {type(e).__name__}", flush=True)
            continue
        for c in chunk:
            try:
                sub = d[f"{c}.T"]
            except (KeyError, TypeError):
                continue
            if "Dividends" in sub.columns:
                s = sub["Dividends"]
                for ts, v in s[s > 0].items():
                    divs.append({"code": c,
                                 "権利落ち日": pd.Timestamp(ts).date(),
                                 "配当": float(v)})
            if "Stock Splits" in sub.columns:
                s = sub["Stock Splits"]
                for ts, v in s[s > 0].items():
                    splits.append({"code": c,
                                   "分割日": pd.Timestamp(ts).date(),
                                   "分割比率": float(v)})
        print(f"  {min(i + CHUNK, len(codes))}/{len(codes)}"
              f"  {time.time() - t0:.0f}秒"
              f"  配当{len(divs):,}件 分割{len(splits):,}件", flush=True)

    dv = pd.DataFrame(divs).sort_values(["code", "権利落ち日"])
    dv.to_csv(OUT_DIR / "dividends.csv", index=False, encoding="utf-8-sig")
    sp = pd.DataFrame(splits).sort_values(["code", "分割日"])
    sp.to_csv(OUT_DIR / "splits.csv", index=False, encoding="utf-8-sig")

    print(f"\n配当: {len(dv):,}件 / {dv['code'].nunique():,}銘柄"
          f"  {dv['権利落ち日'].min()} 〜 {dv['権利落ち日'].max()}")
    print(f"分割: {len(sp):,}件 / {sp['code'].nunique():,}銘柄")
    if len(sp):
        print("  比率の内訳（多い順）")
        for r, n in sp["分割比率"].round(3).value_counts().head(8).items():
            print(f"    {r:>8} : {n:,}件")
    print(f"所要 {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
