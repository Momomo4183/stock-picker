# -*- coding: utf-8 -*-
"""東証の全ETF・ETNの値動きと分配金を、Googleスプレッドシートから読める CSV にして公開する。

2026-10-26 ご本人の依頼: 米国株と同じ形の管理シートを日本株ETF（保有している数本）でも作りたい。
ところが GOOGLEFINANCE は日本のETFの過去の値動きを返さず、チャートが出なかった。そこで、
ここで作った CSV をシートが IMPORTDATA で読む形にした。保有銘柄が外から分からないよう、
保有しているものだけでなく**東証の全ETF・ETN**を出す（どれを持っているかはシートの中だけ）。

出力:
  docs/etf/コード.csv     日付, 終値（直近約400営業日）
  docs/etf/summary.csv    1銘柄1行: コード, 名前, 終値, 前日比%, 52週高値から%, 200日線との差%,
                          週足52週線との差%, 90日騰落%, 1年騰落%, 分配金（直近1年・円）, 分配金利回り%,
                          直近の権利落ち日, 年間の分配回数, 株価の日付
銘柄一覧は JPX の東証上場銘柄一覧（data/jpx_list.xlsx、市場・商品区分が「ETF・ETN」。30日ごとに取り直す）。
値動き・分配金は yfinance（分割調整済み）。

使い方:
    python scripts/build_etf.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "etf"
DAYS = 400


JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
LIST = ROOT / "data" / "jpx_list.xlsx"


def refresh_list(max_age_days: int = 30) -> None:
    """東証上場銘柄一覧を30日ごとに取り直す（失敗したら手元の一覧をそのまま使う）。"""
    import datetime as dt
    import re
    import urllib.request
    if LIST.exists() and dt.date.today() - dt.date.fromtimestamp(LIST.stat().st_mtime) < dt.timedelta(days=max_age_days):
        return
    try:
        ua = {"User-Agent": "Mozilla/5.0"}
        html = urllib.request.urlopen(urllib.request.Request(JPX_PAGE, headers=ua), timeout=60).read().decode("utf-8", "replace")
        url = re.findall(r'href="([^"]+\.xlsx?)"', html)[0]
        url = "https://www.jpx.co.jp" + url if url.startswith("/") else url
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=120).read()
        d = pd.read_excel(__import__("io").BytesIO(raw), dtype=str)
        if "市場・商品区分" not in d.columns:
            raise ValueError("列名が想定と違う")
        d.to_excel(LIST, index=False)
        print(f"  東証上場銘柄一覧を取り直しました（{len(d)}銘柄）", flush=True)
    except Exception as e:
        print(f"  [!] 東証上場銘柄一覧を取り直せませんでした（{type(e).__name__}）。手元の一覧を使います", flush=True)


def etf_list() -> pd.DataFrame:
    refresh_list()
    d = pd.read_excel(LIST, dtype=str)
    return d[d["市場・商品区分"].str.contains("ETF", na=False)][["コード", "銘柄名"]]


def download(codes: list) -> dict:
    import time
    import yfinance as yf
    out = {}

    def fetch(tks, size):
        for i in range(0, len(tks), size):
            chunk = tks[i:i + size]
            d = yf.download(chunk, period="2y", interval="1d", auto_adjust=False, actions=True,
                            progress=False, group_by="ticker", threads=True)
            for tk in chunk:
                try:
                    x = (d[tk] if len(chunk) > 1 else d).dropna(subset=["Close"])
                except KeyError:
                    continue
                if len(x):
                    x.index = pd.DatetimeIndex(x.index).tz_localize(None)
                    out[tk[:-2]] = x

    tks = [f"{c}.T" for c in codes]
    fetch(tks, 100)
    miss = [t for t in tks if t[:-2] not in out]
    if miss:                                   # 取得制限で空になった分を、少し待って取り直す
        print(f"  取れなかった {len(miss)}銘柄を、30秒待って取り直します", flush=True)
        time.sleep(30)
        fetch(miss, 20)
    return out


def pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


def build() -> int:
    lst = etf_list()
    names = dict(zip(lst["コード"], lst["銘柄名"]))
    data = download(lst["コード"].tolist())
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    today = pd.Timestamp.today().normalize()
    for c, x in data.items():
        close = x["Close"]
        if len(close) < 5:
            continue
        close.tail(DAYS).round(2).rename("終値").rename_axis("日付").to_frame().to_csv(
            OUT / f"{c}.csv", date_format="%Y-%m-%d", encoding="utf-8", lineterminator="\n")
        last = float(close.iloc[-1])
        y1 = close[close.index > close.index[-1] - pd.DateOffset(years=1)]
        d90 = close[close.index >= close.index[-1] - pd.Timedelta(days=90)]
        wk = close.resample("W-FRI").last().dropna().tail(52)
        dv = x["Dividends"].fillna(0) if "Dividends" in x else pd.Series(dtype=float)
        dv = dv[dv > 0]
        ttm = float(dv[dv.index > today - pd.Timedelta(days=365)].sum()) if len(dv) else 0.0
        rows.append({
            "コード": c, "名前": names.get(c), "終値": round(last, 2),
            "前日比%": pct(last, float(close.iloc[-2])),
            "52週高値から%": pct(last, float(y1.max())),
            "200日線との差%": pct(last, float(close.tail(200).mean())) if len(close) >= 200 else None,
            "週足52週線との差%": pct(last, float(wk.mean())) if len(wk) >= 52 else None,
            "90日騰落%": pct(last, float(d90.iloc[0])),
            "1年騰落%": pct(last, float(y1.iloc[0])) if close.index[0] <= close.index[-1] - pd.DateOffset(years=1) else None,
            "分配金": round(ttm, 2),
            "分配金利回り%": round(ttm / last * 100, 2) if ttm else 0.0,
            "直近の権利落ち日": dv.index[-1].strftime("%Y-%m-%d") if len(dv) else None,
            "年間の分配回数": int((dv.index > today - pd.Timedelta(days=365)).sum()) if len(dv) else 0,
            "株価の日付": close.index[-1].strftime("%Y-%m-%d"),
        })
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False, encoding="utf-8", lineterminator="\n")
    return len(rows)


if __name__ == "__main__":
    n = build()
    print(f"作成: {OUT}  {n}銘柄")
