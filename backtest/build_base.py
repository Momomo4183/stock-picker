# -*- coding: utf-8 -*-
"""検証の土台を作る。

各銘柄・各週末について「その時点で分かっている指標」と「その後どうなったか」を
1行にまとめる。これが①〜⑥の検証すべての材料になる。

  その時点で分かっている値 … 株価・移動平均からの位置・RSI・週足/月足の傾向など
  その後どうなったか       … 2週間後/1か月後/2か月後/半年後/1年後のリターン、
                              その間の最大含み損（MAE）

先読みを避けるため、指標はすべて**その日の終値まで**で計算する。
リターンは「その日の終値で買った」前提で出す。

生存バイアスの注意: 価格データは現在も上場している3,713銘柄のもので、
途中で上場廃止になった銘柄は入っていない。全体の水準は実際より良く出る。
ただし今回の目的は「リストの中での並べ替えが効くか」＝A'とAの差なので、
生存バイアスはAにもA'にも同じようにかかり、差にはほぼ影響しない。

使い方:
    python backtest/build_base.py            全銘柄（5〜10分）
    python backtest/build_base.py --limit 200  お試し
"""
import datetime as dt
import glob
import gzip
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "backtest"
CACHE_DIR = Path(r"C:\Users\ookin\Documents\Claude\自動トレード\_price_cache")

# 先を見る日数（営業日）。2週間・1か月・2か月・半年・1年
HORIZONS = {"2週": 10, "1月": 21, "2月": 42, "半年": 126, "1年": 252}
# 指標の計算に必要な最低限の長さ（3年分の騰落を使うため）
MIN_ROWS = 780


def load_prices(limit: int | None = None) -> dict:
    """自動トレード側の価格キャッシュから日足を読む。"""
    files = sorted(glob.glob(str(CACHE_DIR / "px_*.pkl.gz")),
                   key=os.path.getmtime)
    if not files:
        raise SystemExit(f"価格キャッシュが見つかりません: {CACHE_DIR}")
    path = files[-1]
    print(f"価格データ: {Path(path).name}", flush=True)
    with gzip.open(path, "rb") as f:
        data = pickle.load(f)
    if limit:
        data = {k: data[k] for k in list(data)[:limit]}
    print(f"  {len(data)}銘柄", flush=True)
    return data


def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    """ページ側(build_site.py)と同じ定義。全日付ぶんを返す。"""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def bad_days(d: pd.DataFrame) -> pd.Series:
    """明らかに壊れている日を見つける。

    yfinance の日本株データには、2,798円の翌日が553億円（8303）のような
    異常値や、再上場前を株価1円で埋めたもの（9201）が混ざっている。
    これらを含んだままだとリターンが桁違いになるため、切り離す。

    分割については何もしなくてよい。yfinance の Close は auto_adjust=False でも
    **すでに分割調整済み**（2026-09-20に確認: 2120の3:1分割日 465→484.5、
    2121の100:1分割日 336→331 と、分割日に飛びが無い）。自前で比率を掛けると
    かえって飛びを作ってしまう。
    """
    c = d["Close"]
    jump = c.pct_change().abs() > 0.6      # 1日で±60%超は壊れた値とみなす
    penny = c < 10                          # 再上場前などの埋め値
    return (jump | penny | c.isna()).fillna(True)


def segments(d: pd.DataFrame) -> list:
    """壊れている日を境にデータを区切り、使える区間だけ返す。"""
    bad = bad_days(d)
    if not bad.any():
        return [d] if len(d) >= MIN_ROWS else []
    grp = bad.cumsum()
    out = []
    for _, seg in d[~bad].groupby(grp[~bad]):
        if len(seg) >= MIN_ROWS:
            out.append(seg)
    return out


def features(d: pd.DataFrame) -> pd.DataFrame | None:
    """1銘柄・1区間ぶんの指標を作る。すべてその日の終値までしか使わない。"""
    if len(d) < MIN_ROWS:
        return None
    c, o = d["Close"], d["Open"]
    h, l, v = d["High"], d["Low"], d["Volume"]
    f = pd.DataFrame(index=d.index)

    f["株価"] = c
    f["売買代金20日"] = (c * v).rolling(20).mean()

    # ── 移動平均からの位置 ────────────────────────────────
    sma5, sma25, sma75 = (c.rolling(n).mean() for n in (5, 25, 75))
    sma65, sma130, sma252 = (c.rolling(n).mean() for n in (65, 130, 252))
    f["5日線乖離%"] = (c - sma5) / sma5 * 100
    f["25日線乖離%"] = (c - sma25) / sma25 * 100
    f["75日線乖離%"] = (c - sma75) / sma75 * 100
    f["13週線乖離%"] = (c - sma65) / sma65 * 100      # 週足13本 ≒ 65営業日
    f["26週線乖離%"] = (c - sma130) / sma130 * 100    # 週足26本 ≒ 半年
    f["12月線乖離%"] = (c - sma252) / sma252 * 100    # 月足12本 ≒ 1年

    # ── 傾向（挙げていただいた「上昇傾向」の候補定義）──────────
    f["26週騰落%"] = c.pct_change(126) * 100          # 週足: 過去半年
    f["52週騰落%"] = c.pct_change(252) * 100          # 月足: 過去1年
    f["3年騰落%"] = c.pct_change(756) * 100           # 月足: 全体的な傾向
    f["13週線の向き"] = (sma65 - sma65.shift(21)) / sma65.shift(21) * 100
    f["12月線の向き"] = (sma252 - sma252.shift(63)) / sma252.shift(63) * 100
    f["MA順位"] = ((c > sma25).astype(int) + (sma25 > sma75).astype(int)
                   + (sma75 > sma252).astype(int))   # 3=パーフェクトオーダー

    # ── 過熱・過冷 ──────────────────────────────────────
    f["RSI14"] = rsi_wilder(c)

    # ── 反転の兆候（複数の定義を並べて、どれが効くかを後で測る）────
    up5 = sma5.diff()
    f["反転_5日線上向き転換"] = ((up5 > 0) & (up5.shift(1) <= 0)).astype(int)
    f["反転_安値切上げ"] = (l.rolling(3).min()
                            > l.shift(3).rolling(3).min()).astype(int)
    f["反転_陰転陽"] = ((c > o) & (c.shift(1) < o.shift(1))).astype(int)
    f["反転_25日線回復"] = ((c > sma25) & (c.shift(1) <= sma25.shift(1))
                            ).astype(int)
    f["連続陽線"] = (c > o).astype(int).groupby(
        (c <= o).cumsum()).cumcount()

    # ── 荒さ（「最悪1年持てるか」に効くと思われる側）───────────
    tr = pd.concat([h - l, (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    f["ATR14%"] = tr.ewm(alpha=1 / 14, adjust=False).mean() / c * 100
    f["20日ボラ%"] = c.pct_change().rolling(20).std() * 100

    # ── 高値・安値からの位置 ─────────────────────────────
    hi52, lo52 = h.rolling(252).max(), l.rolling(252).min()
    f["52週高値まで%"] = (hi52 - c) / c * 100
    f["52週安値から%"] = (c - lo52) / lo52 * 100
    f["出来高比"] = v.rolling(5).mean() / v.rolling(25).mean()

    # ── その後どうなったか ──────────────────────────────
    for name, n in HORIZONS.items():
        f[f"後{name}%"] = (c.shift(-n) / c - 1) * 100
    # 保有中の最大含み損・最大含み益（2か月と1年）
    for name, n in (("2月", 42), ("1年", 252)):
        fwd_lo = l.shift(-1).rolling(n, min_periods=1).min().shift(-(n - 1))
        fwd_hi = h.shift(-1).rolling(n, min_periods=1).max().shift(-(n - 1))
        f[f"MAE{name}%"] = (fwd_lo / c - 1) * 100
        f[f"MFE{name}%"] = (fwd_hi / c - 1) * 100
    return f


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_prices(limit)

    t0, rows, skipped, cut = time.time(), [], 0, 0
    for i, (ticker, d) in enumerate(data.items(), 1):
        code = ticker.replace(".T", "")
        d = d.dropna(subset=["Close"])
        if d.index.tz is not None:
            d.index = d.index.tz_localize(None)
        segs = segments(d)
        if not segs:
            skipped += 1
            continue
        if len(segs) > 1 or len(segs[0]) < len(d):
            cut += 1
        for seg in segs:
            f = features(seg)
            if f is None:
                continue
            # 週1回（金曜、なければその週の最終営業日）だけ残す
            wk = f.groupby(pd.Grouper(freq="W-FRI")).tail(1)
            rows.append(wk.assign(code=code))
        if i % 500 == 0 or i == len(data):
            print(f"  {i}/{len(data)}  {time.time() - t0:.0f}秒", flush=True)

    base = pd.concat(rows).reset_index().rename(columns={"index": "日付"})
    base = base.rename(columns={base.columns[0]: "日付"})
    base["日付"] = pd.to_datetime(base["日付"]).dt.tz_localize(None)
    base["年"] = base["日付"].dt.year
    # float64 のままだと重いので落とす
    for c in base.columns:
        if base[c].dtype == "float64":
            base[c] = base[c].astype("float32")

    out = OUT_DIR / "base_weekly.pkl"
    base.to_pickle(out)
    print(f"\n保存: {out}")
    print(f"  {len(base):,}行 × {len(base.columns)}列")
    print(f"  除外 {skipped}銘柄（使える区間が3年未満）"
          f" / 一部を切り離した銘柄 {cut}件")
    print(f"  期間 {base['日付'].min():%Y-%m-%d} 〜 {base['日付'].max():%Y-%m-%d}")
    print(f"  所要 {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
