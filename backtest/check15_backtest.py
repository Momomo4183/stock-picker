# -*- coding: utf-8 -*-
"""「高配当株 15指標チェック」の点数と、株価の帯で、その後の値動きに差があるかを測る。

ご本人の設計（2026-09-26）:
  1. 日付を選ぶ  2. その日に各条件を判定して10点満点で採点
  3. 8点以上を抽出し、1か月・半年・1年・3年後の株価を見る  4. 繰り返す
  確かめたいこと: 点数の高い銘柄は伸びるか／株価の帯（1,000円未満・1,000〜2,000円・
  2,000〜3,000円・3,000円以上）で伸び方に傾向があるか

日付はランダムに選ぶ代わりに、毎週すべて使う（標本が多いほど偶然に左右されにくい）。
比較の相手は「同じ日の対象（配当利回り3%以上・時価総額300億円以上）全体の平均」。
どの日も同じ土俵で比べるため、日ごとに差を取ってから平均する。

測れる期間の制約:
  点数（Part B）  決算が3期以上そろうのは2024年夏から。yfinance の年次決算は4〜5期しか
                  遡れないため。3年後は測れず、1年後も2024年夏〜2025年夏の分だけ
  株価の帯（Part A）決算が要らないので2012年から。3年後まで測れる

🔴 株価の帯は「当時の実際の株価」で分ける。yfinance の株価は分割調整済みで、後で分割した
銘柄ほど過去の株価が安く表示される。分割するのは値上がりした銘柄なので、調整後の株価で
分けると「安い銘柄ほど上がった」という偽の結果が出る（2026-09-20 に確認済みの罠）。
調整後の株価に、その日より後の分割比率を掛けて当時の株価に戻す。

リターンは株価だけ（配当を含まない）。どの帯も高配当株なので、配当の分（年3〜5%）が
それぞれ上乗せされる。

使い方:
    python backtest/check15_backtest.py          両方
    python backtest/check15_backtest.py --bands  株価の帯だけ（決算書が要らない）
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BT = DATA / "backtest"
OUT = ROOT / "backtest" / "結果"

MIN_YIELD, MIN_CAP = 3.0, 300
BANDS = [(0, 1000, "1,000円未満"), (1000, 2000, "1,000〜2,000円"),
         (2000, 3000, "2,000〜3,000円"), (3000, 1e12, "3,000円以上")]
H_ALL = ["後1月%", "後半年%", "後1年%", "後3年%"]
FINANCE = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}
LAG = pd.Timedelta(days=92)          # 決算は期末から3か月後に使えることにする


def universe() -> pd.DataFrame:
    df = pd.read_pickle(BT / "screened_weekly.pkl")
    u = df[(df["配当利回り%"] >= MIN_YIELD) & (df["時価総額億"] >= MIN_CAP)
           & df["株価"].notna()].copy()
    return u, df


def actual_price(u: pd.DataFrame) -> pd.Series:
    """調整後の株価を、その日の実際の株価に戻す（その日より後の分割比率を掛ける）。"""
    sp = pd.read_csv(BT / "splits.csv", dtype={"code": str}, encoding="utf-8-sig")
    sp["分割日"] = pd.to_datetime(sp["分割日"])
    fac = pd.Series(1.0, index=u.index)
    pos = u.groupby("code").indices
    for code, g in sp.groupby("code"):
        if code not in pos:
            continue
        rows = u.index[pos[code]]
        days = u.loc[rows, "日付"].values
        for d, r in zip(g["分割日"].values, g["分割比率"].values):
            fac.loc[rows[days < d]] *= r
    return u["株価"] * fac


def band_of(p: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=p.index, dtype="object")
    for lo, hi, name in BANDS:
        out[(p >= lo) & (p < hi)] = name
    return out


def rel(g: pd.DataFrame, sel_mask: pd.Series, h: str) -> tuple:
    """日ごとに「選んだ側の平均 − 対象全体の平均」を出し、日を等しく扱って平均する。"""
    x = g[g[h].notna()]
    m = sel_mask.loc[x.index]
    base = x.groupby("日付")[h].mean()
    sel = x[m].groupby("日付")[h].mean()
    d = (sel - base.reindex(sel.index)).dropna()
    by_year = d.groupby(d.index.year).mean()
    return (d.mean() if len(d) else np.nan,
            x[m].groupby("日付")[h].mean().mean() if m.any() else np.nan,
            int((by_year > 0).sum()), len(by_year), int(m.sum()))


# ─────────────────────────────── Part A: 株価の帯（14年）
def part_a(u: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("【A】株価の帯（当時の実際の株価）で、その後の値動きに差があるか  2012〜2026年")
    print(f"    対象: 配当利回り{MIN_YIELD:g}%以上・時価総額{MIN_CAP}億円以上"
          f"（1週あたり平均 {len(u) / u['日付'].nunique():.0f}銘柄）")
    print("=" * 70)
    u = u.assign(実際の株価=actual_price(u))
    u["帯"] = band_of(u["実際の株価"])
    adj_band = band_of(u["株価"])
    moved = (adj_band != u["帯"]).mean() * 100
    print(f"    分割調整後の株価で分けると帯が変わってしまう行: {moved:.1f}%（当時の株価に戻して分けた）")

    mkt = {h: full[full[h].notna()].groupby("日付")[h].mean().mean() for h in H_ALL}
    uni = {h: u[u[h].notna()].groupby("日付")[h].mean().mean() for h in H_ALL}
    print(f"\n  参考: 平均リターン（株価のみ）  "
          + "  ".join(f"{h[1:-1]} 対象全体{uni[h]:+.1f}%／全銘柄{mkt[h]:+.1f}%" for h in H_ALL))
    rows = []
    print(f"\n  {'株価の帯':<14}{'1週の平均銘柄数':>10}" + "".join(f"{h[1:-1] + '（差）':>13}" for h in H_ALL)
          + "   勝った年（1年後）")
    for _, _, name in BANDS:
        mask = u["帯"] == name
        res = {h: rel(u, mask, h) for h in H_ALL}
        n = mask.sum() / u["日付"].nunique()
        y = res["後1年%"]
        print(f"  {name:<14}{n:>10.0f}" + "".join(f"{res[h][0]:>+12.2f}%" for h in H_ALL)
              + f"   {y[2]}/{y[3]}")
        rows.append({"帯": name, "銘柄数/週": round(n, 1),
                     **{f"{h}差": res[h][0] for h in H_ALL},
                     **{f"{h}平均": res[h][1] for h in H_ALL},
                     "1年後の勝ち年": f"{y[2]}/{y[3]}",
                     "平均利回り": u.loc[mask, "配当利回り%"].mean()})
    print("    （差＝その帯の平均 − 同じ日の対象全体の平均。株価のみで配当を含まない）")
    print("\n  帯ごとの平均配当利回り: "
          + "  ".join(f"{r['帯']} {r['平均利回り']:.2f}%" for r in rows))
    return pd.DataFrame(rows)


# ─────────────────────────────── Part B: 15指標の点数
def load_statements() -> dict:
    st = pd.read_csv(DATA / "statements.csv", dtype={"code": str}, encoding="utf-8-sig")
    st = st[st["error"].fillna("") == ""].copy()
    st["決算期"] = pd.to_datetime(st["決算期"])
    st["使用可能日"] = st["決算期"] + LAG
    return {c: g.sort_values("決算期").reset_index(drop=True) for c, g in st.groupby("code")}


def dividends_by_year() -> dict:
    dv = pd.read_csv(BT / "dividends.csv", dtype={"code": str}, encoding="utf-8-sig")
    dv["権利落ち日"] = pd.to_datetime(dv["権利落ち日"])
    return {c: g.groupby(g["権利落ち日"].dt.year)["配当"].sum() for c, g in dv.groupby("code")}


def score_rows(u: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    stm, dy = load_statements(), dividends_by_year()
    sector = pd.read_csv(ROOT / "stocks.csv", dtype={"code": str},
                         encoding="utf-8-sig").set_index("code")["sector"].to_dict()
    ylds = {c: g.set_index("日付")["配当利回り%"].sort_index()
            for c, g in full[["code", "日付", "配当利回り%"]].dropna().groupby("code")}
    out = []
    for code, g in u.groupby("code"):
        s = stm.get(code)
        if s is None:
            continue
        avail = s["使用可能日"].values
        years = dy.get(code)
        yl = ylds.get(code)
        fin = sector.get(code) in FINANCE
        for idx, r in g.iterrows():
            t = r["日付"]
            k = np.searchsorted(avail, np.datetime64(t), side="right")
            if k == 0:
                continue
            f = s.iloc[max(0, k - 5):k]
            last = f.iloc[-1]
            c = {}
            rev, ni = f["売上"].dropna(), f["純利益"].dropna()
            if len(rev) >= 3:
                c["売上"] = rev.iloc[-1] > rev.iloc[0] and (rev.diff().dropna() < 0).sum() <= 1
            if len(ni) >= 3:
                c["利益"] = ni.iloc[-1] > ni.iloc[0] and ni.iloc[-1] > 0
            if pd.notna(last["営業利益"]) and pd.notna(last["売上"]) and last["売上"]:
                c["営業利益率"] = last["営業利益"] / last["売上"] >= 0.05
            cf = f["営業CF"].dropna()
            if len(cf) >= 2:
                c["営業CF"] = bool((cf > 0).all())
            if not fin and pd.notna(last["純資産"]) and pd.notna(last["総資産"]) and last["総資産"]:
                c["自己資本比率"] = last["純資産"] / last["総資産"] >= 0.40
            cap = r["時価総額億"] * 1e8
            if pd.notna(last["純利益"]) and last["純利益"] > 0:
                c["PER"] = cap / last["純利益"] <= 15
                pay = r["配当12月"] * r["株式数推定"] / last["純利益"]
                if pd.notna(pay):
                    c["配当性向"] = 0 < pay <= 0.70
            elif pd.notna(last["純利益"]):
                c["PER"] = False
                c["配当性向"] = False
            if pd.notna(last["純資産"]) and last["純資産"] > 0:
                c["PBR"] = cap / last["純資産"] <= 1
            if years is not None:
                v = years[years.index < t.year].tail(6)
                if len(v) >= 3 and v.iloc[0] > 0:
                    c["配当"] = v.iloc[-1] > v.iloc[0]
            if yl is not None:
                ago = yl.asof(t - pd.Timedelta(days=365))
                if pd.notna(ago) and ago > 0:
                    c["急上昇"] = r["配当利回り%"] / ago < 1.5
            out.append({"idx": idx, "点数": int(sum(c.values())), "判定数": len(c),
                        "成長を判定": "売上" in c and "利益" in c})
    sc = pd.DataFrame(out).set_index("idx")
    return u.join(sc, how="inner")


def part_b(u: pd.DataFrame, full: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("【B】15指標の点数で、その後の値動きに差があるか")
    print("=" * 70)
    s = score_rows(u[u["日付"] >= "2023-06-01"], full)
    # ご本人の設計どおり10点満点で比べるため、売上・利益（決算3期が要る）まで判定でき、
    # 判定できなかった項目が金融業の自己資本比率くらいに収まる行だけを使う
    s = s[s["成長を判定"] & (s["判定数"] >= 9)]
    print(f"    点数を付けられた期間: {s['日付'].min():%Y-%m-%d} 〜 {s['日付'].max():%Y-%m-%d}"
          f"（{s['日付'].nunique()}週・1週あたり平均 {len(s) / s['日付'].nunique():.0f}銘柄）")
    last = s[s["日付"] == s["日付"].max()]
    print(f"    最後の週の点数の分布（今のページと比べる用）: "
          + str({int(k): int(v) for k, v in last["点数"].value_counts().sort_index(ascending=False).items()}))

    hs = ["後1月%", "後半年%", "後1年%"]
    ok_dates = {h: s.loc[s[h].notna(), "日付"] for h in hs}
    print("    測れた期間: " + "  ".join(
        f"{h[1:-1]} {d.min():%Y-%m}〜{d.max():%Y-%m}（{d.nunique()}週）" for h, d in ok_dates.items()))
    print("    3年後: 点数を付けられるのが2024年夏からなので、測れない")

    groups = [("5点以下", s["点数"] <= 5), ("6点", s["点数"] == 6), ("7点", s["点数"] == 7),
              ("8点", s["点数"] == 8), ("9点", s["点数"] == 9), ("10点", s["点数"] == 10),
              ("8点以上", s["点数"] >= 8), ("7点以下", s["点数"] <= 7)]
    print(f"\n  {'点数':<10}{'1週の平均銘柄数':>10}" + "".join(f"{h[1:-1] + '（差）':>12}" for h in hs))
    for name, m in groups:
        res = {h: rel(s, m, h) for h in hs}
        print(f"  {name:<10}{m.sum() / s['日付'].nunique():>10.0f}"
              + "".join(f"{res[h][0]:>+11.2f}%" for h in hs))
    print("    （差＝その点数の平均 − 同じ日の対象全体の平均。株価のみ）")

    s = s.assign(実際の株価=actual_price(s))
    s["帯"] = band_of(s["実際の株価"])
    top = s["点数"] >= 8
    print(f"\n  8点以上の銘柄を、株価の帯で分けると（対象全体との差）")
    print(f"  {'株価の帯':<14}{'1週の平均銘柄数':>10}" + "".join(f"{h[1:-1] + '（差）':>12}" for h in hs))
    for _, _, name in BANDS:
        m = top & (s["帯"] == name)
        res = {h: rel(s, m, h) for h in hs}
        print(f"  {name:<14}{m.sum() / s['日付'].nunique():>10.1f}"
              + "".join(f"{res[h][0]:>+11.2f}%" for h in hs))


def main() -> int:
    OUT.mkdir(exist_ok=True)
    u, full = universe()
    a = part_a(u, full)
    a.to_csv(OUT / "check15_株価の帯.csv", index=False, encoding="utf-8-sig")
    if "--bands" not in sys.argv:
        part_b(u, full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
