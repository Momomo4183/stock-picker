# -*- coding: utf-8 -*-
"""毎月必ず買う前提で、5銘柄のうち「一番安くなっているもの」を選ぶと良いか。

2026-10-11 本人の方針: HDV・KO・SPYD・V・VYM は売らずに毎月何かを買う。どれを買うかを
選ぶ目安として、一番安くなっている銘柄を買う方法を調べる。

比べる相手: 毎月、同じ額を5銘柄に等分して買う。
選び方（毎月の初めに、前の週末までのデータで判定）:
  A 52週高値からの下げが一番大きい
  B 200日線から一番下にいる
  C 1年前からの値動きが一番低い
  D 配当利回りが、その銘柄の過去3年の中で一番高い水準にある（配当に対して一番安い）
値段は配当込み（調整後終値）。Dの利回りは実際の配当（分割調整済み）÷ 株価。
期間を1か月ずつずらして何度も試し、等分に勝った割合を出す。
5銘柄そろうのは2016年10月以降（SPYD上場＋1年分の助走）、SPYDを除く4銘柄は2012年11月以降。

使い方:
    python backtest/pick_cheapest.py
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402


def load(tickers):
    px = yf.download(tickers, start="2010-01-01", auto_adjust=True, progress=False,
                     group_by="ticker")
    raw = yf.download(tickers, start="2007-01-01", auto_adjust=False, actions=True,
                      progress=False, group_by="ticker")
    close = pd.DataFrame({t: px[t]["Close"] for t in tickers}).dropna()
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    feats = {}
    for t in tickers:
        c = close[t]
        r = raw[t].dropna(subset=["Close"])
        r.index = pd.DatetimeIndex(r.index).tz_localize(None)
        ttm = r["Dividends"].fillna(0).rolling("365D").sum()
        yld = (ttm / r["Close"]).reindex(c.index).ffill()
        pct = yld.rolling(756, min_periods=500).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
        feats[t] = pd.DataFrame({
            "A": -(c / c.rolling(252).max() - 1),            # 大きいほど下げている
            "B": -(c / c.rolling(200).mean() - 1),
            "C": -(c / c.shift(252) - 1),
            "D": pct,
        })
    return close, feats


def simulate(close, feats, rule, start, end):
    """毎月1の額を使う。rule=None なら等分。返り値: 最終資産と最後の配分。"""
    days = close.loc[start:end].index
    months = days[days.to_period("M") != pd.Series(days.to_period("M")).shift(1).values]
    shares = pd.Series(0.0, index=close.columns)
    for d in months:
        prev = close.index[close.index.get_loc(d) - 1]
        p = close.loc[d]
        if rule is None:
            shares += (1 / len(p)) / p
        else:
            s = pd.Series({t: feats[t].loc[prev, rule] for t in close.columns})
            if s.isna().all():
                shares += (1 / len(p)) / p
            else:
                t = s.idxmax()
                shares[t] += 1 / p[t]
    val = shares * close.loc[days[-1]]
    return val.sum(), val / val.sum()


def evaluate(tickers, first, years, label):
    close, feats = load(tickers)
    close = close.loc[first:]
    starts = close.index[close.index.to_period("M") != pd.Series(close.index.to_period("M")).shift(1).values]
    starts = [s for s in starts if s + pd.DateOffset(years=years) <= close.index[-1]]
    print(f"\n■ {label}（{years}年の期間 {len(starts)}通り、{starts[0]:%Y-%m}〜{starts[-1]:%Y-%m}に開始）")
    print(f"   {'選び方':<30}{'等分に勝った割合':>10}{'中央値':>8}{'最悪':>8}{'最良':>8}   最後の配分（全期間の例）")
    names = {"A": "A 52週高値からの下げが最大", "B": "B 200日線から一番下",
             "C": "C 1年の値動きが一番低い", "D": "D 利回りが過去3年で一番高い位置"}
    for rule in ["A", "B", "C", "D"]:
        r = []
        for s in starts:
            e = s + pd.DateOffset(years=years)
            v, _ = simulate(close, feats, rule, s, e)
            b, _ = simulate(close, feats, None, s, e)
            r.append(v / b)
        r = np.array(r)
        _, w = simulate(close, feats, rule, starts[0], close.index[-1])
        mix = " ".join(f"{t}{x * 100:.0f}%" for t, x in w.sort_values(ascending=False).items())
        print(f"   {names[rule]:<30}{(r > 1).mean() * 100:>9.0f}%{np.median(r):>8.3f}{r.min():>8.3f}"
              f"{r.max():>8.3f}   {mix}")
    return close


def main() -> int:
    evaluate(["HDV", "KO", "SPYD", "V", "VYM"], "2016-10-01", 5, "5銘柄")
    evaluate(["HDV", "KO", "V", "VYM"], "2012-11-01", 5, "SPYDを除く4銘柄")
    evaluate(["HDV", "KO", "V", "VYM"], "2012-11-01", 10, "SPYDを除く4銘柄・10年")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
