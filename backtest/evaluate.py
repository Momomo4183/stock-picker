# -*- coding: utf-8 -*-
"""追加の選定条件が効いているかを測る。

考え方（ユーザーの設計そのまま）:

  ② その日付でスクリーナーを通す            → A（例: 50銘柄）
  ③ 追加の選定条件で絞る                    → A'（例: 10銘柄）
  ④ 2週間後・1か月後・2か月後・半年後の株価を見る
  ⑤ A' が A より上なら良い条件、下なら悪い条件
  ⑥ これを全期間で回し、年ごとの善し悪しも見る

**比較相手は必ず A の平均**。ゼロと比べると、相場が良い時期はどんな条件でも
良く見えてしまう。`A'平均 − A平均` が、その条件が生んだ差そのもの。

**ランダム並べ替えとの比較**: Aから同じ数だけ適当に選ぶ試行を200回行い、その
散らばりを出す。`A'−A` がその散らばりに埋もれていれば、偶然の範囲でしかない。
過去に58個の特徴量を試して57個が検証期間で脱落した経験があるため、この歯止めを
必ず通す。

使い方:
    python backtest/evaluate.py                既定の条件をまとめて測る
    from evaluate import load, report          個別に呼ぶ
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "backtest"

HORIZONS = ["後2週%", "後1月%", "後2月%", "後半年%", "後1年%"]
SCREENS = {"①": "S1", "②": "S2", "③近似": "S3近似"}
N_SEEDS = 200


def load() -> pd.DataFrame:
    df = pd.read_pickle(DATA / "screened_weekly.pkl")
    return df


def _per_date_mean(g: pd.DataFrame, cols: list) -> pd.Series:
    """日ごとに平均してから、日を等しく扱って平均する。

    候補が多い日に結果が引きずられないようにするため、単純な全行平均は使わない。
    """
    return g.groupby("日付")[cols].mean().mean()


def pick_top(g: pd.DataFrame, col: str, ascending: bool,
             top_n: int) -> pd.DataFrame:
    r = g.groupby("日付")[col].rank(ascending=ascending, method="first")
    return g[r <= top_n]


def random_spread(g: pd.DataFrame, top_n: int, cols: list,
                  seeds: int = N_SEEDS) -> pd.DataFrame:
    """Aから適当にtop_n件選んだときの、A'−A の散らばり。"""
    rng = np.random.default_rng(12345)
    base = _per_date_mean(g, cols)
    out = []
    dates = g["日付"].values
    for _ in range(seeds):
        r = pd.Series(rng.random(len(g)), index=g.index)
        rank = r.groupby(dates).rank(method="first")
        sel = g[rank.values <= top_n]
        out.append(_per_date_mean(sel, cols) - base)
    return pd.DataFrame(out)


def report(df: pd.DataFrame, screen: str, col: str, ascending: bool,
           top_n: int = 10, label: str | None = None,
           min_candidates: int = 3) -> dict:
    """1つの追加条件について、⑤⑥の表を出す。"""
    flag = SCREENS.get(screen, screen)
    g = df[df[flag] & df[col].notna()].copy()
    # 候補が少なすぎる日は絞る意味がないので外す
    n_by_date = g.groupby("日付")["code"].transform("size")
    g = g[n_by_date >= min_candidates]
    if g.empty:
        print(f"  {label or col}: 該当なし")
        return {}

    name = label or f"{col} {'小さい順' if ascending else '大きい順'}"
    a_mean = _per_date_mean(g, HORIZONS)
    sel = pick_top(g, col, ascending, top_n)
    d_mean = _per_date_mean(sel, HORIZONS)
    diff = d_mean - a_mean

    spread = random_spread(g, top_n, HORIZONS)
    sigma = spread.std()

    print(f"\n── {screen}  {name}  （上位{top_n}件）"
          f"  {g['日付'].nunique()}週 / 1週あたり平均{len(g)/g['日付'].nunique():.0f}件")
    print(f"  {'期間':<8}{'A平均':>9}{'A´平均':>9}{'差':>9}"
          f"{'ランダムσ':>11}{'σ何個分':>9}")
    for h in HORIZONS:
        s = sigma[h] if sigma[h] > 0 else np.nan
        print(f"  {h:<8}{a_mean[h]:>8.2f}%{d_mean[h]:>8.2f}%"
              f"{diff[h]:>+8.2f}%{s:>10.2f}%{diff[h]/s:>+9.2f}")
    return {"name": name, "screen": screen, "A": a_mean, "A'": d_mean,
            "差": diff, "σ": sigma, "g": g, "sel": sel}


def by_year(res: dict, horizon: str = "後2月%") -> None:
    """⑥ 期間による善し悪しの違いを見る。"""
    if not res:
        return
    g, sel = res["g"], res["sel"]
    a = g.groupby(["年", "日付"])[horizon].mean().groupby("年").mean()
    d = sel.groupby(["年", "日付"])[horizon].mean().groupby("年").mean()
    diff = (d - a).dropna()
    print(f"\n  年ごとの差（{horizon}）  プラス年 "
          f"{int((diff > 0).sum())}/{len(diff)}")
    print("   " + "".join(f"{int(y):>7}" for y in diff.index))
    print("   " + "".join(f"{v:>+7.1f}" for v in diff.values))


def downside(res: dict) -> None:
    """「最悪1年持てるか」の側を見る。平均では見えない部分。"""
    if not res:
        return
    g, sel = res["g"], res["sel"]
    for nm, x in (("A ", g), ("A'", sel)):
        mae = x.groupby("日付")["MAE1年%"].mean().mean()
        bad = (x["後1年%"] < -20).mean() * 100
        worst = x.groupby("日付")["後1年%"].mean().min()
        print(f"  {nm}: 1年の最大含み損 平均{mae:>7.2f}%   "
              f"1年後に−20%以下 {bad:>5.1f}%   最悪の週 {worst:>7.1f}%")


# チャートの形（価格データだけで出せるので14年ぶん測れる）
TESTS_CHART = [
    ("RSI14", True, "RSI 低い順（高すぎないこと）"),
    ("RSI14", False, "RSI 高い順"),
    ("26週騰落%", False, "週足 過去半年が上昇しているほど上位"),
    ("3年騰落%", False, "月足 全体的に上昇しているほど上位"),
    ("12月線の向き", False, "月足 12か月線が上向きなほど上位"),
    ("MA順位", False, "移動平均の並びが揃っているほど上位"),
    ("ATR14%", True, "値動きが穏やかなほど上位"),
    ("25日線乖離%", True, "押し目が深いほど上位"),
]
# 日足の反転（言葉にしにくい部分なので、4つの形を別々に測る）
TESTS_REVERSAL = [
    ("反転_5日線上向き転換", False, "反転 5日線が上向きに転じた"),
    ("反転_安値切上げ", False, "反転 安値を切り上げた"),
    ("反転_陰転陽", False, "反転 陰線の翌日の陽線"),
    ("反転_25日線回復", False, "反転 25日線を回復した"),
    ("連続陽線", False, "陽線が続いているほど上位"),
    ("52週安値から%", True, "52週安値に近いほど上位"),
    ("52週高値まで%", False, "52週高値から遠いほど上位"),
]
# 決算（2023年以降しか値が無いので、ここだけ標本が薄い）
TESTS_FUND = [
    ("経常前期比%", False, "経常 今期が前期より伸びているほど上位"),
    ("経常連続増益年", False, "経常 連続増益の年数が長いほど上位"),
    ("経常3年伸び%", False, "経常 3年の伸びが大きいほど上位"),
    ("営業前期比%", False, "営業利益 前期比が大きいほど上位"),
    ("売上前期比%", False, "売上 前期比が大きいほど上位"),
    ("ROE%", False, "ROEが高いほど上位"),
    ("営業利益率%", False, "営業利益率が高いほど上位"),
    ("負債比率", True, "有利子負債が少ないほど上位"),
    ("CF利益比", False, "営業CFが利益に見合っているほど上位"),
]
TEST_SETS = {"chart": TESTS_CHART, "reversal": TESTS_REVERSAL,
             "fund": TESTS_FUND}


def main() -> int:
    which = "chart"
    for k in TEST_SETS:
        if f"--{k}" in sys.argv:
            which = k
    tests = TEST_SETS[which]
    df = load()
    print(f"読み込み {len(df):,}行  （{which}）\n")
    for screen in SCREENS:
        print("=" * 66)
        print(f"  スクリーナー {screen}")
        print("=" * 66)
        for col, asc, label in tests:
            if col not in df.columns:
                continue
            res = report(df, screen, col, asc, top_n=10, label=label)
            by_year(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
