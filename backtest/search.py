# -*- coding: utf-8 -*-
"""良い銘柄を選ぶ条件を、母集団から探す。

スクリーナー①②③に縛られず、条件を一から探す。狙いは
「流動性のある全銘柄から上位20件を選び、母集団の平均を上回ること」。

**過去に一度、同じことをして大失敗している。**2026-08-28 に29個の特徴量を
昇順・降順の両方で試し（58通り）、探索期間で最も良かった3つが検証期間で
全滅した（ATR大 +26.6%/年 → −16.1%/年・0勝5敗）。生き残ったのは1つだけ。

そこで今回も最初から2つに割る。**探索期間の結果だけでは絶対に採用しない。**

    探索期間 2012〜2019（8年）… ここで候補を見つける
    検証期間 2020〜2026（7年）… 触らずに取っておく。最後に1度だけ見る

測るのは「上位20件の平均 − 母集団の平均」。母集団の平均＝適当に選んだ場合
なので、この差がその条件の生んだ価値そのものになる。

使い方:
    python backtest/search.py              単独の条件を全部試す
    python backtest/search.py --combo      効いたものを組み合わせる
    python backtest/search.py --downside   下方リスクを測る
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "backtest"
OUT = ROOT / "backtest" / "結果"

HORIZONS = ["後2週%", "後1月%", "後2月%", "後半年%", "後1年%"]
MAIN = "後2月%"              # ご自身の保有期間（2週間〜2か月）の真ん中
TOP_N = 20                   # 10〜20銘柄のピックアップに合わせる
MIN_DAI = 5_000_000          # 売買代金20日平均の下限（現実に買える範囲）
DISCOVER = (2012, 2019)      # 探索期間
CONFIRM = (2020, 2026)       # 検証期間。最後まで見ない

# (列名, 向きの説明) ※昇順・降順の両方を試す
FEATURES = [
    ("5日線乖離%", "短期の位置"),
    ("25日線乖離%", "押し目の深さ"),
    ("75日線乖離%", "中期の位置"),
    ("13週線乖離%", "週足の位置"),
    ("26週線乖離%", "週足の位置"),
    ("12月線乖離%", "月足の位置"),
    ("26週騰落%", "週足 過去半年の傾向"),
    ("52週騰落%", "月足 過去1年の傾向"),
    ("3年騰落%", "月足 全体の傾向"),
    ("13週線の向き", "週足の傾き"),
    ("12月線の向き", "月足の傾き"),
    ("MA順位", "移動平均の並び"),
    ("RSI14", "過熱・過冷"),
    ("反転_5日線上向き転換", "反転の形"),
    ("反転_安値切上げ", "反転の形"),
    ("反転_陰転陽", "反転の形"),
    ("反転_25日線回復", "反転の形"),
    ("連続陽線", "陽線の連続"),
    ("ATR14%", "値動きの荒さ"),
    ("20日ボラ%", "値動きの荒さ"),
    ("52週高値まで%", "高値からの距離"),
    ("52週安値から%", "安値からの距離"),
    ("出来高比", "出来高の増減"),
    ("売買代金20日", "流動性"),
    ("時価総額億", "規模"),
]
# 🔴 株価（水準）は特徴量に入れてはいけない。
# yfinance の株価は分割調整済みなので、**後で分割した銘柄ほど過去の株価が
# 低く表示される**。分割するのは株価が上がった銘柄なので、「株価が低い」は
# 「この先値上がりする」を先読みしていることになる。
# 2026-09-20 の実測: 調整後株価が最も低い20%は 54.3% がその後分割（平均12.99倍）、
# 最も高い20%は 14.5%（1.73倍）。後2月リターンも +3.71% 対 +0.35% と完全に単調。
# 時価総額と売買代金は分割の影響が約分されるので使ってよい（出来高も調整済みで、
# 分割前後の売買代金の比は1.0前後だと確認した）。


def universe(min_cap: float = 0.0) -> pd.DataFrame:
    """流動性で母集団を絞る。min_cap を入れると時価総額の下限もかける。

    **生存バイアスへの備え**: 手元の価格データは現在も上場している銘柄だけで、
    この14年に倒産・上場廃止した銘柄（年100社以上）が入っていない。消えた
    のは小型・低位の銘柄に偏るため、「小さいほど上位」という条件は実際より
    ずっと良く見える。時価総額に下限をかけると、この偏りの大部分を避けられる。
    """
    df = pd.read_pickle(DATA / "screened_weekly.pkl")
    m = (df["売買代金20日"] >= MIN_DAI) & df[MAIN].notna()
    if min_cap > 0:
        m &= df["時価総額億"] >= min_cap
    return df[m].copy()


def per_date(g: pd.DataFrame, cols) -> pd.Series:
    """日ごとに平均してから、日を等しく扱って平均する。"""
    return g.groupby("日付")[cols].mean().mean()


def top_by(g: pd.DataFrame, col: str, ascending: bool, n: int = TOP_N):
    r = g.groupby("日付")[col].rank(ascending=ascending, method="first")
    return g[r <= n]


def combo_score(g: pd.DataFrame, specs: list) -> pd.Series:
    """複数の条件を、その日の中での順位（％）に直して平均する。

    単位の違う指標をそのまま足せないので、いったん全部「その日の候補の中で
    上から何％か」に直してから平均する。

    向きに注意: specs の asc は top_by と同じ意味（True＝小さい順に選ぶ）。
    ここでは**大きいほど良い点数**に揃えたいので、
      ・大きい値を選びたい(asc=False) → ascending=True で大きい値が1.0になる
      ・小さい値を選びたい(asc=True)  → ascending=False で小さい値が1.0になる
    つまり `ascending = not asc`。ここを asc のままにすると全部逆向きになる。
    """
    tot = None
    for col, asc in specs:
        p = g.groupby("日付")[col].rank(pct=True, ascending=not asc)
        tot = p if tot is None else tot + p
    return tot / len(specs)


def yearly(sel: pd.DataFrame, g: pd.DataFrame, h: str = MAIN) -> pd.Series:
    a = sel.groupby(["年", "日付"])[h].mean().groupby("年").mean()
    b = g.groupby(["年", "日付"])[h].mean().groupby("年").mean()
    return (a - b).dropna()


def score(g: pd.DataFrame, sel: pd.DataFrame) -> dict:
    a, b = per_date(sel, HORIZONS), per_date(g, HORIZONS)
    d = a - b
    y = yearly(sel, g)
    return {**{h: d[h] for h in HORIZONS},
            "勝ち年": int((y > 0).sum()), "年数": len(y),
            "週数": g["日付"].nunique()}


def split(u: pd.DataFrame, span: tuple) -> pd.DataFrame:
    return u[(u["年"] >= span[0]) & (u["年"] <= span[1])]


def run_singles(u: pd.DataFrame) -> pd.DataFrame:
    disc = split(u, DISCOVER)
    rows = []
    for col, note in FEATURES:
        if col not in u.columns:
            continue
        g = disc[disc[col].notna()]
        if g.empty:
            continue
        for asc, arrow in ((False, "大きい順"), (True, "小さい順")):
            s = score(g, top_by(g, col, asc))
            rows.append({"特徴量": col, "向き": arrow, "説明": note, **s})
    r = pd.DataFrame(rows).sort_values(MAIN, ascending=False)
    return r


# ── 探索期間(2012〜2019)の結果だけを見て決めた候補 ──────────────
# ここから先は検証期間を見ていない状態で決めている。後から書き換えない。
#
# 探索で分かった形: 「極端に良い条件」は無く、「極端に悪い条件」のほうが
# はっきりしていた。52週安値から遠い / 1年騰落が大きい / 12か月線が上向き —
# これらの上位20件は母集団を 2.3〜2.6% 下回り、8年中2年しか勝てていない。
# 逆向き（小さい順）は +0.2〜0.5% しか得しないので、**順位付けではなく
# 「外す」条件として使うのが筋**だと判断した。
EXCLUDE = [("52週安値から%", 0.80), ("52週騰落%", 0.80),
           ("12月線の向き", 0.80)]      # その日の上位20%を外す

COMBOS = {
    "A 伸び切りを外して13週線乖離で並べる":
        dict(exclude=EXCLUDE, rank=[("13週線乖離%", False)]),
    "B 短期の強さ2つ（13週線乖離+25日線乖離）":
        dict(exclude=[], rank=[("13週線乖離%", False), ("25日線乖離%", False)]),
    "C 探索の上位3つを合成（13週線乖離+RSI+小型）":
        dict(exclude=[], rank=[("13週線乖離%", False), ("RSI14", False),
                               ("時価総額億", True)]),
    "D 外すだけ（並べ替えはしない）":
        dict(exclude=EXCLUDE, rank=[]),
    "E 伸び切りを外して短期の強さ2つで並べる":
        dict(exclude=EXCLUDE, rank=[("13週線乖離%", False),
                                    ("25日線乖離%", False)]),
}


def apply_combo(g: pd.DataFrame, spec: dict, n: int = TOP_N) -> pd.DataFrame:
    """外す条件をかけてから、残りを合成順位で並べて上位n件を取る。"""
    for col, q in spec["exclude"]:
        if col not in g.columns:
            continue
        p = g.groupby("日付")[col].rank(pct=True)
        g = g[(p < q) | p.isna()]
    if not spec["rank"]:
        return g                      # 外すだけの効果を見る
    s = combo_score(g, spec["rank"])
    r = s.groupby(g["日付"]).rank(ascending=False, method="first")
    return g[r <= n]


def downside(g: pd.DataFrame, sel: pd.DataFrame) -> dict:
    """「最悪1年持てるか」の側。平均リターンでは見えない部分。"""
    out = {}
    for nm, x in (("母集団", g), ("選んだ側", sel)):
        y = x[x["後1年%"].notna()]
        out[nm] = {
            "1年の最大含み損": y.groupby("日付")["MAE1年%"].mean().mean(),
            "1年後に−20%以下%": (y["後1年%"] < -20).mean() * 100,
            "1年後にマイナス%": (y["後1年%"] < 0).mean() * 100,
            "2月の最大含み損": y.groupby("日付")["MAE2月%"].mean().mean(),
        }
    return out


def run_combo(u: pd.DataFrame) -> None:
    for span, label in ((DISCOVER, "探索"), (CONFIRM, "検証")):
        g0 = split(u, span)
        print(f"\n【{label}期間 {span[0]}〜{span[1]}】"
              f"  {g0['日付'].nunique()}週")
        print(f"  {'条件':<34}{'件数':>6}{'後1月':>8}{'後2月':>8}"
              f"{'後半年':>8}{'勝ち年':>7}")
        for name, spec in COMBOS.items():
            need = [c for c, _ in spec["rank"]] + [c for c, _ in
                                                   spec["exclude"]]
            g = g0.dropna(subset=[c for c in need if c in g0.columns])
            if g.empty:
                continue
            sel = apply_combo(g, spec)
            s = score(g, sel)
            cnt = len(sel) / sel["日付"].nunique()
            print(f"  {name:<34}{cnt:>6.0f}{s['後1月%']:>+8.2f}"
                  f"{s[MAIN]:>+8.2f}{s['後半年%']:>+8.2f}"
                  f"{str(s['勝ち年']) + '/' + str(s['年数']):>7}")


def run_downside(u: pd.DataFrame) -> None:
    print("\n【下方リスク】全期間（2012〜2026）")
    print(f"  {'条件':<34}{'1年の最大含み損':>16}{'1年後に−20%以下':>17}"
          f"{'1年後にマイナス':>16}")
    for name, spec in list(COMBOS.items()):
        need = [c for c, _ in spec["rank"]] + [c for c, _ in spec["exclude"]]
        g = u.dropna(subset=[c for c in need if c in u.columns])
        if g.empty:
            continue
        sel = apply_combo(g, spec)
        d = downside(g, sel)
        if name == list(COMBOS)[0]:
            b = d["母集団"]
            print(f"  {'（母集団 ＝ 適当に選んだ場合）':<34}"
                  f"{b['1年の最大含み損']:>15.2f}%{b['1年後に−20%以下%']:>16.1f}%"
                  f"{b['1年後にマイナス%']:>15.1f}%")
        s = d["選んだ側"]
        print(f"  {name:<34}{s['1年の最大含み損']:>15.2f}%"
              f"{s['1年後に−20%以下%']:>16.1f}%{s['1年後にマイナス%']:>15.1f}%")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    min_cap = 0.0
    if "--mincap" in sys.argv:
        min_cap = float(sys.argv[sys.argv.index("--mincap") + 1])
    u = universe(min_cap)
    print(f"母集団 {len(u):,}行 / {u['code'].nunique():,}銘柄 "
          f"/ {u['日付'].nunique()}週")
    print(f"  1週あたり平均 {len(u) / u['日付'].nunique():.0f}銘柄"
          f"（売買代金{MIN_DAI / 1e6:.0f}百万円以上"
          + (f"・時価総額{min_cap:.0f}億円以上）" if min_cap else "）"))
    print(f"  探索 {DISCOVER[0]}〜{DISCOVER[1]} / "
          f"検証 {CONFIRM[0]}〜{CONFIRM[1]}（今は見ない）\n")

    if "--combo" in sys.argv:
        run_combo(u)
        return 0
    if "--downside" in sys.argv:
        run_downside(u)
        return 0

    r = run_singles(u)
    tag = f"_cap{int(min_cap)}" if min_cap else ""
    r.to_csv(OUT / f"search_singles{tag}.csv", index=False, encoding="utf-8-sig")
    print(f"【探索期間 {DISCOVER[0]}〜{DISCOVER[1]}】上位20件に絞ったときの"
          f"「母集団平均との差」")
    print(f"  {'特徴量':<16}{'向き':<8}{'後1月':>8}{'後2月':>8}"
          f"{'後半年':>8}{'後1年':>8}{'勝ち年':>8}")
    for _, x in r.head(14).iterrows():
        print(f"  {x['特徴量']:<16}{x['向き']:<8}{x['後1月%']:>+8.2f}"
              f"{x[MAIN]:>+8.2f}{x['後半年%']:>+8.2f}{x['後1年%']:>+8.2f}"
              f"{str(x['勝ち年']) + '/' + str(x['年数']):>8}")
    print("\n  …下位も見る（逆向きが効く可能性があるため）")
    for _, x in r.tail(5).iterrows():
        print(f"  {x['特徴量']:<16}{x['向き']:<8}{x['後1月%']:>+8.2f}"
              f"{x[MAIN]:>+8.2f}{x['後半年%']:>+8.2f}{x['後1年%']:>+8.2f}"
              f"{str(x['勝ち年']) + '/' + str(x['年数']):>8}")
    print(f"\n保存: {OUT / 'search_singles.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
