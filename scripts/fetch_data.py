# -*- coding: utf-8 -*-
"""銘柄ピックアップ用のデータを取得する。

  株価（毎日）    日足6か月を200銘柄ずつまとめて取得。全銘柄で約1分
  財務（週1回）   1社ずつ問い合わせるので遅い。取得制限がかかると30分ほど

PER・PBR・時価総額・配当利回りは「その日の株価 × 1株あたりの値」で出すので、
1株あたりの値（EPS・BPS・株式数・配当）の取り直しは週1回で足りる。
毎日の更新では株価だけを取れば済む。

使い方:
    python scripts/fetch_data.py --prices-only        株価だけ（毎日）
    python scripts/fetch_data.py --fundamentals-only  財務だけ（週1回）
    python scripts/fetch_data.py                      両方
"""
import datetime as dt
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"
TODAY = dt.date.today().strftime("%Y%m%d")

FIELDS = [
    "trailingPE", "forwardPE", "priceToBook",
    "dividendYield", "trailingAnnualDividendYield",
    "dividendRate", "trailingAnnualDividendRate",
    "marketCap", "sharesOutstanding",
    "trailingEps", "forwardEps", "bookValue",
    "currentPrice", "regularMarketPrice", "previousClose",
    "quoteType", "financialCurrency",
]
WORKERS = 8
CHUNK = 200
# 利益がほぼゼロの銘柄は PER が文字列 'Infinity' で返ることがある。数値の列に
# 入れると落ちるので、値なしとして扱う（2026-09-17 に発生）。
BAD_VALUES = {"Infinity", "-Infinity", "NaN", "nan", "inf", "-inf"}


def load_codes() -> pd.DataFrame:
    return pd.read_csv(ROOT / "stocks.csv", dtype={"code": str},
                       encoding="utf-8-sig")


def fetch_info(code: str) -> dict:
    err = ""
    for attempt in range(3):
        try:
            info = yf.Ticker(f"{code}.T").info or {}
            row = {"code": code}
            for k in FIELDS:
                v = info.get(k)
                row[k] = None if isinstance(v, str) and v in BAD_VALUES else v
            row["error"] = ""
            return row
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:150]
            time.sleep(2 * (attempt + 1))
    return {"code": code, "error": err}


def fetch_fundamentals(stocks: pd.DataFrame) -> Path:
    codes = stocks["code"].tolist()
    t0, rows = time.time(), []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_info, c) for c in codes]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if i % 500 == 0 or i == len(codes):
                print(f"  財務 {i}/{len(codes)}  {time.time() - t0:.0f}秒",
                      flush=True)
    fund = pd.DataFrame(rows).merge(stocks, on="code", how="left")
    out = DATA / f"fundamentals_{TODAY}.csv"
    fund.to_csv(out, index=False, encoding="utf-8-sig")
    n_err = int((fund["error"].fillna("") != "").sum())
    print(f"保存: {out.name}  エラー {n_err}件"
          + ("（retry_fundamentals.py で取り直せます）" if n_err else ""),
          flush=True)
    return out


def fetch_prices(stocks: pd.DataFrame) -> Path:
    codes = stocks["code"].tolist()
    t0, frames = time.time(), {}
    for i in range(0, len(codes), CHUNK):
        chunk = codes[i:i + CHUNK]
        try:
            d = yf.download([f"{c}.T" for c in chunk], period="6mo",
                            interval="1d", group_by="ticker",
                            auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print(f"  株価 {i}〜 取得失敗: {type(e).__name__}", flush=True)
            continue
        for c in chunk:
            try:
                sub = d[f"{c}.T"].dropna(how="all")
            except KeyError:
                continue
            if len(sub):
                frames[c] = sub
        print(f"  株価 {min(i + CHUNK, len(codes))}/{len(codes)}"
              f"  {time.time() - t0:.0f}秒", flush=True)
    out = DATA / f"prices_{TODAY}.pkl"
    pd.to_pickle(frames, out)
    print(f"保存: {out.name}  {len(frames)}銘柄", flush=True)
    return out


def main() -> int:
    prices_only = "--prices-only" in sys.argv
    fundamentals_only = "--fundamentals-only" in sys.argv
    DATA.mkdir(exist_ok=True)
    stocks = load_codes()
    print(f"対象 {len(stocks)} 銘柄", flush=True)
    if not prices_only:
        fetch_fundamentals(stocks)
    if not fundamentals_only:
        fetch_prices(stocks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
