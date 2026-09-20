# -*- coding: utf-8 -*-
"""過去の配当履歴を一括で取ってくる（検証用・1回だけ動かせばよい）。

配当利回りは①②の条件に入っているので、過去日のスクリーナーを再現するには
その日時点の「過去12か月の配当合計」が要る。株価と違って配当は
一括ダウンロード(actions=True)で14年分まとめて取れるため、決算数値と違って
期間が短くならない。

出力: data/backtest/dividends.csv  （code, 権利落ち日, 配当）

使い方:
    python backtest/fetch_dividends.py
"""
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "backtest"
OUT = OUT_DIR / "dividends.csv"
START, END = "2011-01-01", "2026-09-01"
CHUNK = 200


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = pd.read_csv(ROOT / "stocks.csv", dtype={"code": str},
                        encoding="utf-8-sig")["code"].tolist()
    print(f"対象 {len(codes)}銘柄", flush=True)

    t0, rows = time.time(), []
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
                s = d[f"{c}.T"]["Dividends"]
            except (KeyError, TypeError):
                continue
            nz = s[s > 0]
            for ts, val in nz.items():
                rows.append({"code": c, "権利落ち日": pd.Timestamp(ts).date(),
                             "配当": float(val)})
        print(f"  {min(i + CHUNK, len(codes))}/{len(codes)}"
              f"  {time.time() - t0:.0f}秒  配当{len(rows):,}件", flush=True)

    df = pd.DataFrame(rows).sort_values(["code", "権利落ち日"])
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n保存: {OUT}")
    print(f"  {len(df):,}件 / {df['code'].nunique():,}銘柄")
    print(f"  期間 {df['権利落ち日'].min()} 〜 {df['権利落ち日'].max()}")
    print(f"  所要 {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
