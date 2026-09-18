# -*- coding: utf-8 -*-
"""fundamentals_*.csv で取得に失敗した銘柄だけを、間隔を空けて取り直す。

一括取得では途中から Yahoo が認証エラー（401 Invalid Crumb など）を返し、
3回の再試行でも取れない銘柄が出る（9/17 は 3,707銘柄中 648）。
欠けたまま件数を出すと、条件に当てはまる銘柄を数え落として
アプリより少なく出るので、並列をやめて1社ずつ取り直す。

使い方:
    python picker/retry_fundamentals.py            最新の fundamentals を上書き更新
    python picker/retry_fundamentals.py --pause 2  1社ごとの待ち秒数（既定 1.0）
"""
import glob
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import FIELDS  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def fetch_once(code: str):
    try:
        info = yf.Ticker(f"{code}.T").info or {}
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:150]
    if not any(info.get(k) is not None for k in ("marketCap", "priceToBook",
                                                  "regularMarketPrice")):
        return None, "主要項目が空"
    # 利益がほぼゼロの銘柄は PER が文字列 'Infinity' で返ることがあり、
    # 数値の列に入れようとして落ちる（9/17 に発生）。値なしとして扱う。
    bad = {"Infinity", "-Infinity", "NaN", "nan", "inf", "-inf"}
    return {k: (None if isinstance(info.get(k), str) and info.get(k) in bad
                else info.get(k)) for k in FIELDS}, ""


def main() -> int:
    pause = 1.0
    if "--pause" in sys.argv:
        pause = float(sys.argv[sys.argv.index("--pause") + 1])
    path = Path(sorted(glob.glob(str(DATA / "fundamentals_*.csv")))[-1])
    df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    todo = df.index[df["error"].fillna("") != ""].tolist()
    print(f"{path.name}: 取り直し {len(todo)} 銘柄（1社ごとに {pause}秒待つ）",
          flush=True)

    t0, ok, backoff = time.time(), 0, pause
    for n, idx in enumerate(todo, 1):
        code = df.at[idx, "code"]
        vals, err = fetch_once(code)
        if vals is None:
            # 連続して弾かれたら待ち時間を延ばす（最大30秒）
            backoff = min(backoff * 2, 30.0)
            time.sleep(backoff)
            vals, err = fetch_once(code)
        if vals is not None:
            for k, v in vals.items():
                df.at[idx, k] = v
            df.at[idx, "error"] = ""
            ok += 1
            backoff = pause
        else:
            df.at[idx, "error"] = err
        if n % 50 == 0 or n == len(todo):
            print(f"  {n}/{len(todo)}  成功 {ok}  {time.time() - t0:.0f}秒",
                  flush=True)
            df.to_csv(path, index=False, encoding="utf-8-sig")   # 途中経過も保存
        time.sleep(pause)

    df.to_csv(path, index=False, encoding="utf-8-sig")
    left = int((df["error"].fillna("") != "").sum())
    print(f"保存: {path.name}  成功 {ok} / 残る失敗 {left}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
