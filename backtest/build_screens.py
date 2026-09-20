# -*- coding: utf-8 -*-
"""過去の各週末について、スクリーナー①②③を再現する。

build_base.py が作った週次の指標表に、その時点で**すでに発表されていた**
決算数値と配当をくっつけて、PER・PBR・時価総額・配当利回りを出す。

  PER      = その日の株価 ÷ 直近に発表済みのEPS
  PBR      = その日の株価 ÷ (純資産 ÷ 株式数)
  時価総額 = その日の株価 × 株式数
  配当利回り = 直近12か月の配当合計 ÷ その日の株価

先読み防止: 決算数値は `使用可能日`（期末＋3か月）以降でしか使わない。
配当は権利落ち日が過ぎたものだけを数える。

③の近似について: 信用倍率はJPXが5週分しか公開しておらず過去に遡れないため、
**③からは信用倍率の条件を外している**。他の4条件（時価総額・売買代金・
25日線乖離・RSI）はそのまま。

使い方:
    python backtest/build_screens.py
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "backtest"


def as_ns(s: pd.Series) -> pd.Series:
    """日付の刻み（秒/マイクロ秒）を揃える。merge_asof が型の違いを嫌うため。"""
    return pd.to_datetime(s).astype("datetime64[ns]")


def split_factor(fund: pd.DataFrame) -> pd.Series:
    """決算期の株式数を「今の株数基準」に直すための倍率。

    株価と配当は yfinance が分割調整済みで返す（＝今の株数に揃っている）のに、
    決算書の株式数・EPSは当時のまま。そのままPERやPBRを計算すると分割の
    回数だけずれる。決算期より後に起きた分割の比率を株式数に掛けて基準を
    揃える。

    例: 2022年3月期の株式数1億株 → その後1:5分割 → 今の基準では5億株
    """
    sp = pd.read_csv(DATA / "splits.csv", dtype={"code": str},
                     encoding="utf-8-sig")
    sp["分割日"] = pd.to_datetime(sp["分割日"])
    by_code = {k: v.sort_values("分割日") for k, v in sp.groupby("code")}

    out = np.ones(len(fund))
    codes = fund["code"].values
    ends = fund["決算期"].values
    for i in range(len(fund)):
        g = by_code.get(codes[i])
        if g is None:
            continue
        later = g.loc[g["分割日"].values > ends[i], "分割比率"]
        if len(later):
            out[i] = float(later.prod())
    return pd.Series(out, index=fund.index)


def add_growth(fund: pd.DataFrame) -> pd.DataFrame:
    """決算期ごとに「伸びているか」を出す。

    ユーザーが経常利益で見ている観点のうち、過去データで測れる2つ:
      ・実績が年々伸びているか      → 連続増益年数、3年の伸び
      ・今期が昨年に比べて伸びたか  → 前期比

    経常利益そのものは yfinance に無いため **税引前利益で代用**する
    （経常利益 ≒ 税引前利益 − 特別損益）。

    「最新会社予想が前期と比べて上か下か」は測れない。yfinance は過去の
    会社予想を保持しておらず、現時点のアナリスト予想しか返さないため。

    伸び率は前期がプラスのときだけ出す（赤字からの回復を「+300%」の
    ように扱うと順位付けが壊れるため）。
    """
    fund = fund.sort_values(["code", "決算期"]).copy()
    g = fund.groupby("code")

    for col, name in (("税引前利益", "経常"), ("営業利益", "営業"),
                      ("売上", "売上")):
        prev = g[col].shift(1)
        fund[f"{name}前期比%"] = ((fund[col] / prev - 1) * 100).where(prev > 0)

    prev3 = g["税引前利益"].shift(3)
    fund["経常3年伸び%"] = (((fund["税引前利益"] / prev3) ** (1 / 3) - 1)
                            * 100).where(prev3 > 0)

    # 連続して増益だった年数（今期を含めて何期連続で増えているか）
    up = (fund["税引前利益"] > g["税引前利益"].shift(1)).astype(int)
    streak = up.groupby([fund["code"], (up == 0).cumsum()]).cumsum()
    fund["経常連続増益年"] = streak

    # 潰れにくさ・稼ぐ力の側（「最悪1年持てるか」に効くと思われるもの）
    fund["ROE%"] = (fund["純利益"] / fund["純資産"] * 100).where(
        fund["純資産"] > 0)
    fund["営業利益率%"] = (fund["営業利益"] / fund["売上"] * 100).where(
        fund["売上"] > 0)
    fund["負債比率"] = (fund["有利子負債"] / fund["純資産"]).where(
        fund["純資産"] > 0)
    fund["CF利益比"] = (fund["営業CF"] / fund["純利益"]).where(
        fund["純利益"] > 0)
    return fund


def attach_fundamentals(base: pd.DataFrame) -> pd.DataFrame:
    """その時点で発表済みの決算数値を各行にくっつける。"""
    fund = pd.read_csv(DATA / "fundamentals_history.csv", dtype={"code": str},
                       encoding="utf-8-sig")
    fund = fund[fund["error"].fillna("") == ""].copy()
    fund["使用可能日"] = as_ns(fund["使用可能日"])
    fund["決算期"] = as_ns(fund["決算期"])
    fund = fund.dropna(subset=["使用可能日", "決算期"])
    fund["株式数調整"] = fund["株式数"] * split_factor(fund)
    fund = add_growth(fund)
    fund = fund.sort_values("使用可能日")

    cols = ["EPS", "税引前利益", "営業利益", "売上", "純利益", "純資産",
            "株式数", "株式数調整", "有利子負債", "営業CF",
            "経常前期比%", "営業前期比%", "売上前期比%", "経常3年伸び%",
            "経常連続増益年", "ROE%", "営業利益率%", "負債比率", "CF利益比"]
    keep = ["code", "使用可能日", "決算期"] + cols
    fund = fund[[c for c in keep if c in fund.columns]]

    base = base.assign(日付=as_ns(base["日付"])).sort_values("日付")
    out = pd.merge_asof(base, fund, left_on="日付", right_on="使用可能日",
                        by="code", direction="backward")
    return out


def attach_dividends(df: pd.DataFrame) -> pd.DataFrame:
    """直近12か月の配当合計を出す（権利落ち済みのものだけ）。"""
    div = pd.read_csv(DATA / "dividends.csv", dtype={"code": str},
                      encoding="utf-8-sig")
    div["権利落ち日"] = as_ns(div["権利落ち日"])
    div = div.sort_values(["code", "権利落ち日"])
    div["累計配当"] = div.groupby("code")["配当"].cumsum()
    div = div.sort_values("権利落ち日")

    df = df.assign(日付=as_ns(df["日付"])).sort_values("日付")
    # 今日までの累計 − 1年前までの累計 ＝ 直近12か月の配当
    now = pd.merge_asof(df[["日付", "code"]], div[["権利落ち日", "code",
                                                   "累計配当"]],
                        left_on="日付", right_on="権利落ち日", by="code",
                        direction="backward")["累計配当"]
    ago = df[["日付", "code"]].copy()
    ago["1年前"] = ago["日付"] - pd.Timedelta(days=365)
    ago = ago.sort_values("1年前")
    past = pd.merge_asof(ago, div[["権利落ち日", "code", "累計配当"]],
                         left_on="1年前", right_on="権利落ち日", by="code",
                         direction="backward")
    past = past.sort_index()["累計配当"]

    df = df.reset_index(drop=True)
    df["配当12月"] = (now.reset_index(drop=True).fillna(0)
                      - past.reset_index(drop=True).fillna(0))
    # 配当の記録が1件も無い銘柄は「無配」ではなく「不明」として扱う
    has = set(div["code"].unique())
    df.loc[~df["code"].isin(has), "配当12月"] = np.nan
    return df


def main() -> int:
    t0 = time.time()
    base = pd.read_pickle(DATA / "base_weekly.pkl")
    print(f"土台 {len(base):,}行", flush=True)

    df = attach_fundamentals(base)
    print(f"決算数値をくっつけました  {time.time() - t0:.0f}秒", flush=True)
    df = attach_dividends(df)
    print(f"配当をくっつけました      {time.time() - t0:.0f}秒", flush=True)

    # PER・PBRは「1株あたり」ではなく合計どうしの比で出す。こうすると
    # 分割による株数基準のずれが約分されて消える。
    #   PER = 時価総額 ÷ 純利益 （= 株価 ÷ EPS と同じもの）
    #   PBR = 時価総額 ÷ 純資産
    # 時価総額だけは、決算が取れない古い期間にも遡って出す。
    # 株式数は分割を除けば年に数%しか動かない（利益や純資産と違う）ので、
    # その銘柄で一番古く分かっている株式数を、それ以前にも当てはめる。
    # ③は利益を使わないので、これで14年ぶん検証できるようになる。
    df = df.sort_values(["code", "日付"])
    df["株式数推定"] = df.groupby("code")["株式数調整"].bfill()
    df["株数は推定"] = df["株式数調整"].isna() & df["株式数推定"].notna()

    price = df["株価"]
    cap = price * df["株式数推定"]
    df["時価総額億"] = cap / 1e8
    cap_strict = price * df["株式数調整"]
    # PER/PBR は推定株数を使わない（利益・純資産は当時の実績が要るため）
    df["PER"] = (cap_strict / df["純利益"]).where(df["純利益"] > 0)
    df["PBR"] = (cap_strict / df["純資産"]).where(df["純資産"] > 0)
    df["BPS"] = df["純資産"] / df["株式数調整"]
    df["配当利回り%"] = df["配当12月"] / price * 100

    per, pbr = df["PER"], df["PBR"]
    div, cap = df["配当利回り%"], df["時価総額億"]
    rsi, kairi = df["RSI14"], df["25日線乖離%"]
    dai = df["売買代金20日"]

    # ① PER12以下・PBR1以下・配当利回り3%以上・時価総額700億以上
    df["S1"] = ((per <= 12) & (pbr <= 1) & (div >= 3) & (cap >= 700))
    # ② PER7以下・PBR0.8以下・配当利回り3%未満
    df["S2"] = ((per <= 7) & (pbr <= 0.8) & (div < 3))
    # ③ 時価総額300億以上・売買代金5百万以上・25日線乖離0〜1%・RSI25〜60
    #    （信用倍率2.5倍以下は過去データが無いため外している）
    df["S3近似"] = ((cap >= 300) & (dai >= 5_000_000)
                    & (kairi >= 0) & (kairi <= 1)
                    & (rsi >= 25) & (rsi <= 60))
    for c in ("S1", "S2", "S3近似"):
        df[c] = df[c].fillna(False)

    out = DATA / "screened_weekly.pkl"
    df.to_pickle(out)

    print(f"\n保存: {out}   {time.time() - t0:.0f}秒")
    ok = df["PER"].notna() & df["PBR"].notna()
    print(f"  PER/PBRが出せた行: {ok.sum():,} / {len(df):,}"
          f"  （{ok.mean() * 100:.1f}%）")
    print("\n  年ごとの該当件数（週あたりの平均）")
    print(f"  {'年':>6} {'①':>8} {'②':>8} {'③近似':>8} {'母集団':>9}")
    for y, g in df.groupby("年"):
        w = g["日付"].nunique()
        print(f"  {y:>6} {g['S1'].sum()/w:>8.1f} {g['S2'].sum()/w:>8.1f}"
              f" {g['S3近似'].sum()/w:>8.1f} {len(g)/w:>9.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
