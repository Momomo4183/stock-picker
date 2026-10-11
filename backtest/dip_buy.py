# -*- coding: utf-8 -*-
"""売らずに買い増す銘柄で、「下がったときに買う」と「毎月定額で買う」のどちらが良いか。

2026-10-11 本人の方針: HDV・KO・SPYD・V・VYM は売らずに、下がったときに買い増す。
その「下がったとき」の目安として何が良いかを調べる。

比べ方（どれも同じお金を使う）
  毎月定額  毎月1の額を、月の最初の週に必ず買う
  下がったら 毎月1の額を現金で貯めておき、条件を満たした週に貯めた分をまとめて買う
            待っている間の現金には米ドルの短期金利（^IRX）がつく
  最後に、持っている株と残った現金を合わせた額で比べる。

「下がった」の条件（週1回、週の最終営業日の終値で判定）
  52週高値から−10% / −20% / 200日線より下 / RSI(14)30以下 / 週足52週線より下

値段は配当込み（yfinance の調整後終値）。ドル建て（為替はどの買い方にも同じようにかかる）。
10年の期間を1か月ずつずらして何度も試し、定額に勝った割合と、勝ち負けの幅を出す。

使い方:
    python backtest/dip_buy.py
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

TICKERS = ["KO", "V", "VYM", "HDV", "SPYD"]
YEARS = 10


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def weekly_frame(close: pd.Series, irx: pd.Series) -> pd.DataFrame:
    """日足から指標を作り、週の最終営業日だけを残す。"""
    wk = close.index.to_period("W-FRI")
    last = close.groupby(wk).tail(1).index
    wclose = close.loc[last]
    f = pd.DataFrame({"close": wclose})
    f["dd52"] = (close / close.rolling(252).max() - 1).loc[last]
    f["below200"] = (close < close.rolling(200).mean()).loc[last]
    f["rsi"] = rsi(close).loc[last]
    f["below52w"] = wclose < wclose.rolling(52).mean()
    f["rate"] = irx.reindex(last).ffill().fillna(0).values / 52     # 1週分の金利
    f["new_month"] = f.index.to_period("M") != pd.Series(f.index.to_period("M")).shift(1).values
    return f.dropna(subset=["dd52"])


RULES = {
    "52週高値から−10%": lambda f: f["dd52"] <= -0.10,
    "52週高値から−20%": lambda f: f["dd52"] <= -0.20,
    "200日線より下": lambda f: f["below200"],
    "RSI30以下": lambda f: f["rsi"] <= 30,
    "週足52週線より下": lambda f: f["below52w"],
}


def run(f: pd.DataFrame, cond: np.ndarray | None):
    """cond=None なら毎月定額。返り値: 最後の資産額、現金で待っていた週の割合。"""
    px, rate, nm = f["close"].values, f["rate"].values, f["new_month"].values
    shares = cash = 0.0
    waited = 0
    for i in range(len(px)):
        cash *= 1 + rate[i]
        if nm[i]:
            cash += 1.0
        if cond is None:
            if nm[i]:
                shares += cash / px[i]
                cash = 0.0
        elif cond[i] and cash > 0:
            shares += cash / px[i]
            cash = 0.0
        if cash > 0:
            waited += 1
    return shares * px[-1] + cash, waited / len(px)


def main() -> int:
    irx = yf.download("^IRX", start="1960-01-01", progress=False)["Close"].squeeze() / 100
    irx.index = pd.DatetimeIndex(irx.index).tz_localize(None)
    print(f"10年ずつ、1か月ずらしで比較。数字は「下がったら買う」÷「毎月定額」の最終資産（1.00より上なら勝ち）\n")
    summary = []
    for tk in TICKERS:
        c = yf.download(tk, start="1960-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        c.index = pd.DatetimeIndex(c.index).tz_localize(None)
        f = weekly_frame(c, irx.reindex(c.index).ffill())
        starts = f.index[f["new_month"].values]
        starts = [s for s in starts if s + pd.DateOffset(years=YEARS) <= f.index[-1]]
        if not starts:
            continue
        print(f"■ {tk}（データ {c.index[0]:%Y}〜、10年の期間 {len(starts)}通り）")
        for name, rule in RULES.items():
            ratios, waits = [], []
            for s in starts:
                w = f[(f.index >= s) & (f.index < s + pd.DateOffset(years=YEARS))]
                base, _ = run(w, None)
                v, wt = run(w, rule(w).fillna(False).values)
                ratios.append(v / base)
                waits.append(wt)
            r = np.array(ratios)
            summary.append({"銘柄": tk, "条件": name, "勝率": (r > 1).mean(), "中央値": np.median(r),
                            "最悪": r.min(), "最良": r.max(), "待ち": np.mean(waits)})
            print(f"   {name:<14} 勝った割合 {(r > 1).mean() * 100:5.1f}%   中央値 {np.median(r):.3f}"
                  f"   最悪 {r.min():.3f}   最良 {r.max():.3f}   現金で待っていた週 {np.mean(waits) * 100:4.0f}%")
        print()
    s = pd.DataFrame(summary)
    print("■ 5銘柄の平均")
    for name in RULES:
        x = s[s["条件"] == name]
        print(f"   {name:<14} 勝った割合 {x['勝率'].mean() * 100:5.1f}%   中央値 {x['中央値'].mean():.3f}"
              f"   現金で待っていた週 {x['待ち'].mean() * 100:4.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
