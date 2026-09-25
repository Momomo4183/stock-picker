# -*- coding: utf-8 -*-
"""15指標チェック用に、銘柄ごとの決算書（年次・4〜5期分）を取ってくる。

    損益計算書  売上・営業利益・純利益
    貸借対照表  総資産・純資産・現金
    CF計算書    営業キャッシュフロー

決算は四半期ごとにしか変わらないので、取得してから30日間は使い回す。
今回の対象で、まだ取っていない銘柄と30日より古い銘柄だけを取りにいく。
yfinance は1社ずつの問い合わせで取得制限がかかりやすいので、失敗した銘柄は
間を空けてもう一度だけ取り直す。

出力: data/statements.csv（code, 決算期, 各項目, 取得日）

使い方（普段は build_check15.py から呼ばれる）:
    python scripts/fetch_statements.py 7203 8591 ...
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "statements.csv"
MAX_AGE_DAYS = 30
WORKERS = 6

# (出力の列名, 候補の項目名（上から順に探す）, 表)
FIELDS = [
    ("売上", ["Total Revenue", "Operating Revenue"], "income"),
    ("営業利益", ["Operating Income", "Total Operating Income As Reported"], "income"),
    ("純利益", ["Net Income Common Stockholders", "Net Income"], "income"),
    ("総資産", ["Total Assets"], "balance"),
    ("純資産", ["Stockholders Equity", "Common Stock Equity"], "balance"),
    ("現金", ["Cash And Cash Equivalents",
              "Cash Cash Equivalents And Short Term Investments"], "balance"),
    ("営業CF", ["Operating Cash Flow"], "cash"),
]


def fetch_one(code: str) -> list:
    today = dt.date.today().isoformat()
    for attempt in range(2):
        try:
            t = yf.Ticker(f"{code}.T")
            tables = {"income": t.income_stmt, "balance": t.balance_sheet,
                      "cash": t.cashflow}
            if tables["income"] is None or tables["income"].empty:
                return [{"code": code, "取得日": today, "error": "財務諸表なし"}]
            periods = sorted({c for df in tables.values()
                              if df is not None and not df.empty for c in df.columns})
            rows = []
            for p in periods:
                row = {"code": code, "決算期": pd.Timestamp(p).date().isoformat(),
                       "取得日": today, "error": ""}
                for name, keys, which in FIELDS:
                    df, v = tables[which], None
                    if df is not None and p in df.columns:
                        for k in keys:
                            if k in df.index and pd.notna(df.loc[k, p]):
                                v = float(df.loc[k, p])
                                break
                    row[name] = v
                rows.append(row)
            return rows
        except Exception as e:
            err = f"{type(e).__name__}"[:60]
            time.sleep(3 * (attempt + 1))
    return [{"code": code, "取得日": today, "error": err}]


def load() -> pd.DataFrame:
    if OUT.exists():
        return pd.read_csv(OUT, dtype={"code": str}, encoding="utf-8-sig")
    return pd.DataFrame(columns=["code", "決算期", "取得日", "error"])


def update(codes: list) -> pd.DataFrame:
    """対象の銘柄について、無い・古い・前回失敗した分だけ取り直す。"""
    old = load()
    fresh_cut = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    ok = old[(old["error"].fillna("") == "") & (old["取得日"] >= fresh_cut)]
    todo = [c for c in codes if c not in set(ok["code"])]
    if not todo:
        print(f"  決算書: {len(codes)}銘柄とも{MAX_AGE_DAYS}日以内に取得済み", flush=True)
        return old
    print(f"  決算書: {len(todo)}銘柄を取得します（{len(codes) - len(todo)}銘柄は取得済み）",
          flush=True)
    t0, rows = time.time(), []
    for pass_no in (1, 2):
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(fetch_one, c) for c in todo]
            for i, f in enumerate(as_completed(futs), 1):
                rows.extend(f.result())
                if i % 100 == 0 or i == len(todo):
                    print(f"    {i}/{len(todo)}  {time.time() - t0:.0f}秒", flush=True)
        failed = {r["code"] for r in rows if r.get("error") not in ("", "財務諸表なし")}
        if not failed or pass_no == 2:
            break
        print(f"    取得制限などで{len(failed)}銘柄が失敗。30秒おいて取り直します", flush=True)
        time.sleep(30)
        rows = [r for r in rows if r["code"] not in failed]
        todo = sorted(failed)
    new = pd.DataFrame(rows)
    keep = old[~old["code"].isin(new["code"])]
    out = pd.concat([keep, new], ignore_index=True)
    OUT.parent.mkdir(exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    n_err = new.loc[new["error"].fillna("") != "", "code"].nunique()
    print(f"  保存: {OUT.name}（失敗・データなし {n_err}銘柄）", flush=True)
    return out


if __name__ == "__main__":
    update(sys.argv[1:])
