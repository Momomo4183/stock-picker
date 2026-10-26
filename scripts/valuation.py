# -*- coding: utf-8 -*-
"""PER と PER×PBR を、その銘柄自身の過去と比べるための共通処理。

2026-10-18 期待値投資のページで PER の幅（過去10年の毎月のPERの下から1割・中央値・上から1割）を作り、
2026-10-26 ご本人の依頼で PER×PBR も同じ形で過去と比べられるようにした。

毎月の値の作り方:
  PER     ＝ 月末の株価 ÷ その時点で発表済みの直近の通期EPS
  PBR     ＝ 月末の株価 ÷ その時点で発表済みの直近の通期BPS
  PER×PBR ＝ PER × PBR（株価² ÷（EPS×BPS））
  EPS・BPS は有価証券報告書（EDINET）の通期の値を、株式分割を今の基準に直したもの（build_renzoku.adjust）。
  決算発表は期末の約3か月後として扱う。EPS や BPS がマイナスの月は空欄。
今の値は、今の株価 ÷ 直近の通期EPS・BPS（グラフと同じ物差しにそろえる。ページの PBR は四半期の
純資産から出しているので、少し違うことがある）。
"""
import time

import numpy as np
import pandas as pd

QS = (0.1, 0.5, 0.9)


def monthly_prices(codes: list) -> dict:
    """月末の株価（11年分）。取得制限で空になった銘柄は、少し待って取り直す。

    2026-10-19 の更新で、1銘柄だけ取得制限で空の株価が返り、期待値投資のページ全体が止まった。
    空の銘柄は結果に入れず、待ってから数銘柄ずつ取り直す（それでも取れなければその銘柄だけ飛ばす）。
    """
    import yfinance as yf
    out = {}

    def fetch(tks, size):
        for i in range(0, len(tks), size):
            chunk = tks[i:i + size]
            d = yf.download(chunk, period="11y", interval="1mo", auto_adjust=False, progress=False,
                            group_by="ticker", threads=True)
            for tk in chunk:
                try:
                    s = (d[tk] if len(chunk) > 1 else d)["Close"].dropna()
                except KeyError:
                    continue
                if len(s):
                    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
                    out[tk[:-2]] = s

    tks = [f"{c}.T" for c in codes]
    fetch(tks, 100)
    for wait in (30, 90):
        miss = [t for t in tks if t[:-2] not in out]
        if not miss:
            break
        print(f"  月末の株価が取れなかった {len(miss)}銘柄を、{wait}秒待って取り直します", flush=True)
        time.sleep(wait)
        fetch(miss, 20)
    return out


def monthly_table(close: pd.Series, a: dict) -> pd.DataFrame:
    """毎月の 株価・EPS・PER・BPS・PBR・PER×PBR（過去10年、古い順。今月は月末前なので入れない）。"""
    known_at = [(pd.Timestamp(fy + "-01") + pd.offsets.MonthEnd(0) + pd.DateOffset(months=3)) for fy in a["fy"]]

    def known(vals):
        s = pd.Series(vals, index=known_at).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        return s.reindex(close.index.union(s.index)).ffill().reindex(close.index)

    df = pd.DataFrame({"株価": close, "EPS": known(a["EPS"]), "BPS": known(a["BPS"])}).dropna(subset=["株価", "EPS"])
    df = df[df.index >= close.index[-1] - pd.DateOffset(years=10)]
    df = df[df.index.to_period("M") < pd.Timestamp.today().to_period("M")]
    df["PER"] = (df["株価"] / df["EPS"]).where(df["EPS"] > 0)
    df["PBR"] = (df["株価"] / df["BPS"]).where(df["BPS"] > 0)
    df["PERxPBR"] = df["PER"] * df["PBR"]
    return df


def band(values: pd.Series, now, years: int = 10, min_n: int = 36):
    """直近 years 年の毎月の値の、下から1割・中央値・上から1割と、今の位置。"""
    v = values.tail(years * 12).dropna()
    if len(v) < min_n or now is None:
        return None
    lo, mid, hi = (float(np.quantile(v, q)) for q in QS)
    return {"lo": round(lo, 1), "mid": round(mid, 1), "hi": round(hi, 1), "now": round(now, 1),
            "pos": round((now - lo) / (hi - lo) * 100) if hi > lo else None}


def bands(close: pd.Series, a: dict, price_now: float) -> dict:
    """PER と PER×PBR の幅（過去10年）と、今の値・グラフ用の月次の値。"""
    if close is None or len(close) == 0 or not a or not a.get("fy"):
        return {}
    t = monthly_table(close, a)
    eps, bps = a["EPS"][-1], a["BPS"][-1]
    per_now = price_now / eps if eps and eps > 0 else None
    pbr_now = price_now / bps if bps and bps > 0 else None
    pp_now = per_now * pbr_now if per_now is not None and pbr_now is not None else None
    out = {}
    for key, col, now in (("PER", "PER", per_now), ("PERxPBR", "PERxPBR", pp_now)):
        b = band(t[col], now)
        if b:
            b["series"] = [[d.strftime("%Y-%m"), round(float(x), 1)] for d, x in t[col].dropna().items()]
            out[key] = b
    out["PBR今"] = round(pbr_now, 2) if pbr_now is not None else None
    return out
