# -*- coding: utf-8 -*-
"""過去の決算数値を銘柄ごとに取ってくる（検証用・1回だけ動かせばよい）。

yfinance の年次財務諸表から、決算期ごとに次を拾う。

  Basic EPS              → 過去のPER を「その日の株価 ÷ EPS」で出すのに使う
  Stockholders Equity    → 1株純資産(BPS) → 過去のPBR
  Ordinary Shares Number → 過去の株式数 → 過去の時価総額
  Pretax Income          → 経常利益の代用（yfinance に経常利益そのものは無い）
  Operating Income       → 営業利益率
  Total Revenue          → 売上（成長率）
  Total Debt             → 有利子負債（潰れにくさ）
  Operating Cash Flow    → 営業CF（利益の質）

**先読みを避けるしくみ**: 決算の数字は決算期末には分からない。日本企業の
本決算発表は期末からおよそ45日後なので、安全側に倒して**期末＋3か月**から
使えることにする（`使用可能日` 列）。検証ではこの日以降でしか参照しない。

取れるのは4〜5年ぶん（銘柄により2年のこともある）。これが案Aの検証期間の
上限になる。

途中で止まっても再開できる（取得済みの銘柄は飛ばす）。

使い方:
    python backtest/fetch_history_fundamentals.py
    python backtest/fetch_history_fundamentals.py --limit 50   お試し
"""
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "backtest"
OUT = OUT_DIR / "fundamentals_history.csv"

WORKERS = 8
# (出力列名, 財務諸表での名前, どの表か)
FIELDS = [
    ("EPS", "Basic EPS", "income"),
    ("EPS希薄", "Diluted EPS", "income"),
    ("税引前利益", "Pretax Income", "income"),
    ("営業利益", "Operating Income", "income"),
    ("売上", "Total Revenue", "income"),
    ("純利益", "Net Income", "income"),
    ("純資産", "Stockholders Equity", "balance"),
    ("株式数", "Ordinary Shares Number", "balance"),
    ("有利子負債", "Total Debt", "balance"),
    ("営業CF", "Operating Cash Flow", "cash"),
]
# 本決算の発表は期末からおよそ45日後。安全側に倒して3か月後から使う。
DISCLOSURE_LAG_DAYS = 92


def fetch_one(code: str) -> list:
    err = ""
    for attempt in range(3):
        try:
            t = yf.Ticker(f"{code}.T")
            tables = {}
            for key, attr in (("income", "income_stmt"),
                              ("balance", "balance_sheet"),
                              ("cash", "cashflow")):
                df = getattr(t, attr)
                tables[key] = df if df is not None and not df.empty else None
            if tables["income"] is None:
                return [{"code": code, "error": "財務諸表なし"}]

            periods = sorted({c for df in tables.values() if df is not None
                              for c in df.columns})
            rows = []
            for p in periods:
                row = {"code": code, "決算期": pd.Timestamp(p).date(),
                       "error": ""}
                for out_name, src_name, which in FIELDS:
                    df = tables[which]
                    v = None
                    if df is not None and src_name in df.index \
                            and p in df.columns:
                        raw = df.loc[src_name, p]
                        if pd.notna(raw):
                            v = float(raw)
                    row[out_name] = v
                rows.append(row)
            return rows
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:150]
            time.sleep(2 * (attempt + 1))
    return [{"code": code, "error": err}]


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stocks = pd.read_csv(ROOT / "stocks.csv", dtype={"code": str},
                         encoding="utf-8-sig")
    codes = stocks["code"].tolist()
    if limit:
        codes = codes[:limit]

    done, old = set(), None
    if OUT.exists():
        old = pd.read_csv(OUT, dtype={"code": str}, encoding="utf-8-sig")
        done = set(old.loc[old["error"].fillna("") == "", "code"])
        print(f"取得済み {len(done)}銘柄は飛ばします")
    todo = [c for c in codes if c not in done]
    print(f"対象 {len(todo)}銘柄  （全{len(codes)}）", flush=True)
    if not todo:
        print("すべて取得済みです。")
        return 0

    t0, rows = time.time(), []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, c) for c in todo]
        for i, f in enumerate(as_completed(futs), 1):
            rows.extend(f.result())
            if i % 250 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  {time.time() - t0:.0f}秒",
                      flush=True)

    new = pd.DataFrame(rows)
    if old is not None:
        keep = old[old["code"].isin(done)]
        new = pd.concat([keep, new], ignore_index=True)
    # 決算期＋3か月を「その数字を使ってよい日」とする
    new["決算期"] = pd.to_datetime(new["決算期"], errors="coerce")
    new["使用可能日"] = new["決算期"] + pd.Timedelta(days=DISCLOSURE_LAG_DAYS)
    new = new.sort_values(["code", "決算期"])
    new.to_csv(OUT, index=False, encoding="utf-8-sig")

    ok = new[new["error"].fillna("") == ""]
    n_err = new["code"].nunique() - ok["code"].nunique()
    print(f"\n保存: {OUT}")
    print(f"  {len(ok):,}行 / {ok['code'].nunique():,}銘柄"
          f"  （失敗 {n_err}銘柄）")
    if len(ok):
        per_code = ok.groupby("code")["決算期"].count()
        print(f"  1銘柄あたりの決算期数: 中央値 {per_code.median():.0f}"
              f"  最小 {per_code.min()}  最大 {per_code.max()}")
        print(f"  決算期の範囲 {ok['決算期'].min():%Y-%m}"
              f" 〜 {ok['決算期'].max():%Y-%m}")
    print(f"  所要 {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
