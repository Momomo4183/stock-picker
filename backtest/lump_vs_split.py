# -*- coding: utf-8 -*-
"""手元のドルを、今まとめて買うか、何回かに分けて買うか。

2026-10-16 本人の迷い: スプレッドシートで買う銘柄は決まるが、手元のドルを全部まとめて
買うか、次回以降のために残して分けて買うか。
比べ方: 同じ額を (1) 初月に全部買う (2) N か月に等分して毎月買う（待っている分の現金には
米ドル短期金利 ^IRX がつく）。N か月後（分けて買い終わった時点）の資産で比べる。
対象は5銘柄の等分（2015-11〜）と、SPYD を除く4銘柄（2008〜）。値段は配当込み。

使い方:
    python backtest/lump_vs_split.py
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402


def monthly(tickers, start):
    px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"][tickers].dropna()
    px.index = pd.DatetimeIndex(px.index).tz_localize(None)
    irx = yf.download("^IRX", start=start, progress=False)["Close"].squeeze() / 100
    irx.index = pd.DatetimeIndex(irx.index).tz_localize(None)
    first = px.groupby(px.index.to_period("M")).head(1)          # 毎月の最初の営業日
    ret = first.pct_change().fillna(0).mean(axis=1)              # 毎月等分に配分し直すかご
    idx = (1 + ret).cumprod()
    rate = irx.reindex(first.index, method="ffill").fillna(0).values / 12
    return idx.values, rate, first.index


def compare(idx, rate, dates, n):
    out = []
    for s in range(len(idx) - n):
        lump = idx[s + n] / idx[s]
        cash, shares = 1.0, 0.0
        for k in range(n):
            buy = 1.0 / n if k < n - 1 else cash
            buy = min(buy, cash)
            shares += buy / idx[s + k]
            cash -= buy
            cash *= 1 + rate[s + k]
        split = shares * idx[s + n] + cash
        out.append((dates[s], lump, split))
    return pd.DataFrame(out, columns=["開始", "まとめて", "分けて"])


def main() -> int:
    for label, tk, start in [("5銘柄の等分", ["HDV", "KO", "SPYD", "V", "VYM"], "2015-11-01"),
                             ("SPYDを除く4銘柄", ["HDV", "KO", "V", "VYM"], "2008-04-01")]:
        idx, rate, dates = monthly(tk, start)
        print(f"\n■ {label}（{dates[0]:%Y-%m}〜{dates[-1]:%Y-%m}）")
        for n in (3, 6, 12, 24):
            r = compare(idx, rate, dates, n)
            d = r["まとめて"] / r["分けて"] - 1
            worst = r.loc[d.idxmin()]
            print(f"  {n:>2}か月に分ける: まとめて買いが勝った割合 {(d > 0).mean()*100:4.0f}%  差の中央値 {d.median()*100:+5.1f}%"
                  f"  まとめてが一番負けた時 {d.min()*100:+5.1f}%（{worst['開始']:%Y-%m}開始）"
                  f"  一番勝った時 {d.max()*100:+5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
