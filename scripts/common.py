# -*- coding: utf-8 -*-
"""各ページで共通に使うデータの読み込み（株価・1株あたりの値・配当の履歴）。

2026-10-18 まで「配当株の買い場」（docs/index.html）を作っていた build_site.py から、
ページを作る部分を除いて残したもの（ページはご本人の依頼で削除）。

定義の確認済み事項（2026-09-17 スーパースクリーナーとの突き合わせ）:
    PER は実績。配当利回りは予想（dividendRate ÷ 株価）
2026-11-11 配当利回り・配当性向を「実績」に変えた（ご本人の決定）。yfinance の予想配当（dividendRate）は
    年1回配当の銘柄を2倍にするなど、配当のある銘柄の約17%で実績の1.6倍以上になっていた
    （ヤマト 1967: 予想91円が182円、カゴメ 2811: 588円）。今は
      配当   ＝ 直近の通期の1株配当（「配当（10期）」と同じ。yfinance の配当履歴を期ごとに合計、
               無い期は有価証券報告書の値。分割は今の株数に直してある）
      配当性向 ＝ その配当 ÷ 同じ期の EPS（有価証券報告書。summary.csv の EPS 列と同じ）
      配当利回り ＝ その配当 ÷ 今の株価
    元は build_per_data.py が書く data/dividend_actual.json。無い銘柄は yfinance の
    過去12か月の配当（trailingAnnualDividendRate）÷ 過去12か月のEPS（trailingEps）で補う。
"""
import json
import glob
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"
# 各ページの上に並べるリンク（2026-10-26 高配当株 15指標・グロース株のページを削除）
NAV = [("./", "トップ"), ("renzoku.html", "連続増配株"), ("kitaichi.html", "期待値投資"),
       ("common.html", "共通する銘柄")]


def latest(pattern: str) -> Path:
    files = sorted(glob.glob(str(DATA / pattern)))
    if not files:
        raise FileNotFoundError(f"{pattern} がありません")
    return Path(files[-1])


def atr_pct(d: pd.DataFrame, n: int = 14) -> float:
    c, h, l = d["Close"], d["High"], d["Low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    v = tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1] / c.iloc[-1] * 100
    return float(v) if pd.notna(v) else np.nan


DIV_ACTUAL = DATA / "dividend_actual.json"
DIV_MAX_AGE_DAYS = 550     # 直近の通期がこれより古い（報告書が見つからない等）なら使わない
DIV_MAX_YIELD = 0.3        # 配当が株価のこの割合を超えたら取り違えとみなす


def save_dividend_actual(rows: dict) -> None:
    """{コード: {"fy": "YYYY-MM", "DPS": 値, "EPS": 値}} を data/dividend_actual.json に足す。"""
    cur = json.loads(DIV_ACTUAL.read_text(encoding="utf-8")) if DIV_ACTUAL.exists() else {}
    cur.update(rows)
    DIV_ACTUAL.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")


def dividend_actual() -> pd.DataFrame:
    """銘柄ごとの直近の通期の配当と EPS（code, 実績配当, 実績EPS, 配当の期）。"""
    if not DIV_ACTUAL.exists():
        return pd.DataFrame(columns=["code", "実績配当", "実績EPS", "配当の期"])
    limit = (pd.Timestamp.today() - pd.Timedelta(days=DIV_MAX_AGE_DAYS)).strftime("%Y-%m")
    rows = [{"code": c, "実績配当": v.get("DPS"), "実績EPS": v.get("EPS"), "配当の期": v.get("fy")}
            for c, v in json.loads(DIV_ACTUAL.read_text(encoding="utf-8")).items()
            if (v.get("fy") or "") >= limit]
    return pd.DataFrame(rows)


def load() -> tuple:
    f_fund, f_px = latest("fundamentals_*.csv"), latest("prices_*.pkl")
    fund = pd.read_csv(f_fund, dtype={"code": str}, encoding="utf-8-sig")
    rows = []
    for code, d in pd.read_pickle(f_px).items():
        d = d.dropna(subset=["Close"])
        if len(d) < 26:
            continue
        rows.append({"code": code, "株価": float(d["Close"].iloc[-1]),
                     "終値日": str(d.index[-1].date()), "ATR%": atr_pct(d)})
    px = pd.DataFrame(rows)
    # 荒さは全銘柄の中での位置（0＝最も穏やか、100＝最も荒い）
    px["荒さ"] = px["ATR%"].rank(pct=True) * 100
    df = fund.merge(px, on="code", how="left")

    # PER・PBR・時価総額・配当利回りは「その日の株価 × 1株あたりの値」で出す。
    # 2026-09-18 検算: yfinance が返す値との一致は PER 99.8% / PBR 99.9% /
    # 時価総額 99.8% が誤差1%以内。
    price = df["株価"]
    df["PER"] = (price / df["trailingEps"]).where(df["trailingEps"] > 0)
    df["PBR"] = (price / df["bookValue"]).where(df["bookValue"] > 0)
    df["時価総額億"] = price * df["sharesOutstanding"] / 1e8
    for col, src in (("PER", "trailingPE"), ("PBR", "priceToBook")):
        df[col] = df[col].fillna(df[src])
    df["時価総額億"] = df["時価総額億"].fillna(df["marketCap"] / 1e8)
    # 配当は実績（上の説明）。報告書の値が無い銘柄だけ yfinance の過去12か月で補う
    df = df.merge(dividend_actual(), on="code", how="left")
    has = df["実績配当"].notna()
    df["配当"] = pd.to_numeric(df["実績配当"].where(has, df["trailingAnnualDividendRate"]), errors="coerce")
    df["配当EPS"] = pd.to_numeric(df["実績EPS"].where(has, df["trailingEps"]), errors="coerce")
    # 株価の3割を超える配当は取り違え（テンアライド 8207: 報告書の配当 40,118円は優先株の分。普通株は無配）。
    # yfinance の過去12か月で補い、それもおかしければ空欄にする
    tr = pd.to_numeric(df["trailingAnnualDividendRate"], errors="coerce")
    odd = df["配当"] > price * DIV_MAX_YIELD
    df.loc[odd, "配当"] = tr.where(tr <= price * DIV_MAX_YIELD)[odd]
    df.loc[odd, "配当EPS"] = pd.to_numeric(df["trailingEps"], errors="coerce")[odd]
    has = has & ~odd
    df["配当の出どころ"] = np.where(has, "報告書", np.where(df["配当"].notna(), "yfinance過去12か月", ""))
    df["配当利回り%"] = df["配当"] / price * 100
    df["配当性向%"] = (df["配当"] / df["配当EPS"] * 100).where(df["配当EPS"] > 0)
    asof = {"株価": str(px["終値日"].max()), "財務": f_fund.stem.split("_")[-1]}
    return df, asof


def dividend_history(codes: list) -> dict:
    """候補の銘柄だけ、6年分の株価と配当履歴を取って配当の材料を作る。

    株価も配当も yfinance が分割調整済みで返すので、そのまま割り算してよい。
    """
    import yfinance as yf
    out = {}
    if not codes:
        return out
    tks = [f"{c}.T" for c in codes]
    frames = {}
    for i in range(0, len(tks), 150):          # 一度に多く頼むと失敗しやすい
        chunk = tks[i:i + 150]
        d = yf.download(chunk, period="7y", interval="1d", group_by="ticker",
                        actions=True, auto_adjust=False, progress=False,
                        threads=True)
        for tk in chunk:
            try:
                frames[tk] = d[tk] if len(chunk) > 1 else d
            except KeyError:
                pass
    today = pd.Timestamp.today().normalize()
    for c, tk in zip(codes, tks):
        sub = frames.get(tk)
        if sub is None:
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty or "Dividends" not in sub:
            continue
        sub.index = pd.DatetimeIndex(sub.index).tz_localize(None)
        close, dv = sub["Close"], sub["Dividends"].fillna(0)
        rec = {}

        # 割安度: 直近1年の配当 ÷ 株価 を毎週出し、今の値が過去5年の何％点か
        ttm = dv.rolling("365D").sum()
        yld = (ttm / close).resample("W-FRI").last()
        start = today - pd.DateOffset(years=5)
        full = yld[(yld.index >= start)
                   & (yld.index >= close.index[0] + pd.Timedelta(days=365))]
        if len(full) >= 104 and full.iloc[-1] > 0:        # 2年分以上あるとき
            rec["割安度"] = float((full.iloc[:-1] < full.iloc[-1]).mean() * 100)
        # 利回りの前年比: 今の利回り ÷ 1年前の利回り。株価の急落で利回りが
        # 急に高くなった銘柄を見分ける（15指標チェックで使う）
        ago = yld[yld.index <= today - pd.DateOffset(years=1)]
        if len(ago) and ago.iloc[-1] > 0 and len(yld) and yld.iloc[-1] > 0:
            rec["利回り前年比"] = float(yld.iloc[-1] / ago.iloc[-1])

        # 減配・連続増配: 暦年ごとの配当合計（今年は途中なので使わない）
        paid = dv[dv > 0]
        yearly = paid.groupby(paid.index.year).sum()
        # 取得を始めた年は途中からしか入っていないので使わない（使うと、その年の
        # 配当が少なく見え、次の年が「増配」、伸びが数倍に見えてしまう。
        # 2026-09-25 トヨタの5年の伸びが+352%と出て発覚）。今年も途中なので使わない
        yearly = yearly[(yearly.index > close.index[0].year)
                        & (yearly.index < today.year)].tail(6)
        if len(yearly) >= 3:
            v = yearly.values
            rec["減配"] = int(sum(v[i] < v[i - 1] * 0.97
                                 for i in range(1, len(v))))
            streak = 0
            for i in range(len(v) - 1, 0, -1):
                if v[i] > v[i - 1] * 1.001:
                    streak += 1
                else:
                    break
            rec["連続増配"] = streak
            if v[0] > 0:                 # 最も古い年と直近の年の比（中長期で増えたか）
                rec["配当の伸び"] = float(v[-1] / v[0])

        # 権利月: 直近13か月の権利落ち日の月
        recent = paid[paid.index >= today - pd.DateOffset(months=13)]
        if len(recent):
            rec["権利月"] = "・".join(str(m) for m in
                                      sorted(set(recent.index.month)))
        out[c] = rec
    return out
