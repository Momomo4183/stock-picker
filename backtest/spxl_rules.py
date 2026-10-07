# -*- coding: utf-8 -*-
"""SPXL を手動で売買するときの「目安」になる単純なルールを探す。

2026-10-07 本人の方針:
  SPXL は余剰資金で売買する（3倍レバレッジは長期の持ちっぱなしに向かないため）。
  手動なので必ず従うわけではないが、「RSIが70を超えたら売りの目安」程度の
  単純な指針がほしい。厳密・複雑な条件にはしない。

試し方:
  買いの目安（現金のとき）× 売りの目安（持っているとき）の組み合わせを全部試す。
  判定は週1回（金曜の終値）を基本にし、翌営業日の終値で売買したことにする。
  比べる期間は3つ:
    3倍の近似・前半 1994〜2009（ITバブル崩壊・リーマンショックを含む）
    3倍の近似・後半 2010〜2026（強い上げ相場が中心）
    実物のSPXL 2009〜2026
  3倍の近似 = S&P500(SPY)の日々のリターン×3 − 借入コスト（短期金利×2）− 経費率1%/年。
  実物と比べると18年で1.22倍とやや良く出る（どのルールにも同じようにかかる）。
  現金のときは短期金利（^IRX）がつく。

税金: 特定口座の約20.315%。売ったときに利益が出ていればその分を払う（損失の繰越は
入れない＝売買の多いルールに少し厳しめ）。持ちっぱなしは最後にまとめて払う。

前半と後半の両方で効くものだけを候補にする（過去にだけ合うルールを避けるため）。

使い方:
    python backtest/spxl_rules.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

TAX = 0.20315
OUT = Path(__file__).resolve().parent / "結果"


def load():
    spy = yf.download("SPY", start="1993-01-29", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    irx = (yf.download("^IRX", start="1993-01-01", progress=False)["Close"].squeeze()
           .reindex(spy.index).ffill().fillna(0) / 100)
    spxl = yf.download("SPXL", start="2008-11-05", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    r = spy.pct_change().fillna(0)
    sim = (1 + (3 * r - 2 * irx / 252 - 0.01 / 252)).cumprod()
    return spy, irx, spxl, sim


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


BUYS = {
    "B1 200日線より上": lambda f: f["above"],
    "B2 200日線より上でRSI40以下": lambda f: f["above"] & (f["rsi"] <= 40),
    "B3 RSI30以下": lambda f: f["rsi"] <= 30,
    "B4 1年の高値から−20%": lambda f: f["dd52"] <= -0.20,
}
SELLS = {
    "S1 200日線を下回る": ("cond", lambda f: ~f["above"]),
    "S2 RSI70以上": ("cond", lambda f: f["rsi"] >= 70),
    "S3 RSI80以上": ("cond", lambda f: f["rsi"] >= 80),
    "S4 最高値から−25%": ("trail", 0.25),
    "S5 買値から+50%": ("profit", 0.50),
}


def simulate(price, feats, irx, buy, sell, weekly=True):
    """買い・売りの目安に従った場合の、税引前と税引後の資産の推移。"""
    idx = price.index
    f = feats.reindex(idx)
    bsig = BUYS[buy](f).fillna(False).values
    kind, rule = SELLS[sell]
    ssig = rule(f).fillna(False).values if kind == "cond" else None
    # 週1回 = 週の最終営業日（金曜が休みの週は木曜）
    wk = pd.Series(idx, index=idx).dt.to_period("W-FRI")
    check = (wk != wk.shift(-1)).values if weekly else np.ones(len(idx), bool)
    p = price.values
    cash_r = irx.reindex(idx).fillna(0).values / 252
    eq_pre = eq_post = 1.0
    hold, entry_v, peak = False, 0.0, 0.0
    pre, post, n_buy = [], [], 0
    pending = None                       # 判定の翌営業日に売買する
    for i in range(len(idx)):
        if i > 0:
            if hold:
                g = p[i] / p[i - 1]
                eq_pre *= g
                eq_post *= g
                peak = max(peak, eq_post)
            else:
                eq_pre *= 1 + cash_r[i]
                eq_post *= 1 + cash_r[i]
        if pending == "buy":
            hold, entry_v, peak, n_buy = True, eq_post, eq_post, n_buy + 1
        elif pending == "sell":
            gain = eq_post - entry_v
            if gain > 0:
                eq_post -= gain * TAX
            hold = False
        pending = None
        if check[i]:
            if not hold and bsig[i]:
                pending = "buy"
            elif hold:
                if kind == "cond" and ssig[i]:
                    pending = "sell"
                elif kind == "trail" and eq_post <= peak * (1 - rule):
                    pending = "sell"
                elif kind == "profit" and eq_post >= entry_v * (1 + rule):
                    pending = "sell"
        pre.append(eq_pre)
        post.append(eq_post)
    pre, post = pd.Series(pre, index=idx), pd.Series(post, index=idx)
    if hold:                               # 最後に持っていれば、その時点で売ったことにして税を引く
        gain = post.iloc[-1] - entry_v
        if gain > 0:
            post.iloc[-1] -= gain * TAX
    return pre, post, n_buy


def stats(s):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1, (s / s.cummax() - 1).min(), yrs


def main() -> int:
    OUT.mkdir(exist_ok=True)
    spy, irx, spxl, sim = load()
    feats = pd.DataFrame({"above": spy > spy.rolling(200).mean(), "rsi": rsi(spy),
                          "dd52": spy / spy.rolling(252).max() - 1})
    periods = [("前半", sim, "1994-01-01", "2009-12-31"), ("後半", sim, "2010-01-01", "2026-12-31"),
               ("実物", spxl, "2009-01-01", "2026-12-31")]
    rows = []
    for weekly in (True, False):
        for b in BUYS:
            for s in SELLS:
                rec = {"判定": "週1回" if weekly else "毎日", "買い": b, "売り": s}
                for name, price, a, z in periods:
                    p = price[a:z]
                    pre, post, n = simulate(p, feats, irx, b, s, weekly)
                    c, dd, yrs = stats(pre)
                    ca, _, _ = stats(post)
                    rec.update({f"{name}年率": c, f"{name}税引後": ca, f"{name}最大下げ": dd,
                                f"{name}買い回数/年": n / yrs})
                rows.append(rec)
    res = pd.DataFrame(rows)
    # 持ちっぱなし
    base = {}
    for name, price, a, z in periods:
        p = price[a:z] / price[a:z].iloc[0]
        c, dd, yrs = stats(p)
        post = p.copy()
        post.iloc[-1] = 1 + (p.iloc[-1] - 1) * (1 - TAX)
        base[name] = (c, stats(post)[0], dd)
    res.to_csv(OUT / "spxl_rules.csv", index=False, encoding="utf-8-sig")

    print("持ちっぱなし（税引前 / 税引後 / 最大の下げ）")
    for name, (c, ca, dd) in base.items():
        print(f"  {name}: {c*100:5.1f}% / {ca*100:5.1f}% / {dd*100:6.1f}%")
    w = res[res["判定"] == "週1回"].copy()
    # 前半・後半の両方で効くか: 税引後の年率の低いほうで並べる
    w["弱いほうの税引後"] = w[["前半税引後", "後半税引後"]].min(axis=1)
    w = w.sort_values("弱いほうの税引後", ascending=False)
    print("\n【週1回の判定】税引後の年率（前半・後半の弱いほうの順）")
    print(f"  {'買いの目安':<26}{'売りの目安':<16}{'前半':>14}{'後半':>14}{'実物':>14}{'買い/年':>7}")
    for _, x in w.iterrows():
        cell = lambda n: f"{x[n+'税引後']*100:5.1f}%/{x[n+'最大下げ']*100:5.0f}%"
        print(f"  {x['買い']:<26}{x['売り']:<16}{cell('前半'):>14}{cell('後半'):>14}{cell('実物'):>14}"
              f"{x['実物買い回数/年']:>7.1f}")
    print("    （各期間: 税引後の年率 / 最大の下げ）")
    d = res[res["判定"] == "毎日"].set_index(["買い", "売り"])
    ww = w.set_index(["買い", "売り"])
    diff = (ww["後半税引後"] - d["後半税引後"]).mean() * 100
    diff2 = (ww["前半税引後"] - d["前半税引後"]).mean() * 100
    print(f"\n毎日判定との差（週1回 − 毎日、税引後の年率の平均）: 前半 {diff2:+.1f}pt  後半 {diff:+.1f}pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
