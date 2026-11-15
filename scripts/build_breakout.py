# -*- coding: utf-8 -*-
"""新高値ブレイクのページ（docs/breakout.html）を作る。2026-11-15 ご本人の依頼で追加。

ご本人のまとめ（新高値ブレイク投資法.xlsx）の手順と、このページで自動にしたところ:
  1. 新高値銘柄を見つける（過去半年・1年・2年の3期間で新高値）
       → 直近5営業日のどこかで、その日の高値が「その日より前の半年／1年／2年の最高値」を超えた銘柄。
         どの期間を超えたかを ○ で表示。上場から期間に満たない銘柄は、上場来の最高値を超えたら「上場来」。
  2. チャートの形を確かめる（ダーバスのボックス理論・オニールのカップウィズハンドル・出来高の急増）
       → 目安だけ出す（最後は本人がチャートで確かめる。グラフを押すと大きく表示）
         ボックス  新高値の日の前に、高値と安値の幅が12%以内でもみ合っていた期間（20営業日以上）
         カップ    7〜52週前の山（A）から12〜50%下げて戻した形。山の後に安値圏で3週以上過ごした
                   （V字でなくU字）ものだけ。直前5週に、Aの85%以上の山から3〜15%の押し（取っ手）があれば「＋取っ手」
         出来高    新高値の日の出来高 ÷ その前50営業日の平均。2倍以上を「急増」
  3. ビッグチェンジの理由を探す
       → 自動では判断できないので、ニュース・決算のページへのリンクを置く（株探・楽天証券）
  4. 業績（通期＋四半期）。ご本人の資料「ファンダメンタルズ確認の4つのポイント」
       ① 1年ごとの業績の安定性   過去3年の営業利益の伸び（年率）。10%以上 ◎、5%以上 ○
       ② 直近1〜2年の営業利益の伸び  直近の通期の前期比。30%以上 ◎（理想）・20%以上 ○（基準）・10%以上 △（最低）
       ③ 四半期の営業利益と売上高の伸び（最も重要）
            直近の2〜3四半期が前年同期比で営業利益20%以上・売上10%以上
            → 四半期の数字は EDINET に無い（2024年4月に四半期報告書がなくなった）。東証の適時開示（TDnet）は
              robots.txt で自動取得を断っているので使わない。yfinance の四半期は2割が空・半数近くが古い（2026-11-15 に確認）。
              そこで「半期」で代用する: 半期報告書（上期）と有価証券報告書（通期）から、
              上期＝半期報告書の値、下期＝通期−上期 として、直近の2つの半期をそれぞれ前年同期と比べる。
              2つとも満たせば ◎、直近だけなら ○。前年同期が赤字で今期が黒字なら「黒字化」として満たす扱い
       ④ 売上高営業利益率の伸び  直近の通期の営業利益率が前期より上がり、売上も増えていれば ○
     資料の注記「③が最も重要（③を満たせば他は無くてもよい）」「赤字でもビッグチェンジによる成長を見込むことがある」
     に合わせ、赤字や業績の条件で銘柄を外さない。並びは ③ → ② の順。

数字の出どころ:
  株価  日足6か月（fetch_data.py の prices_*.pkl）＋ 週足2年（ここで取る data/weekly_2y.pkl。全銘柄で約1分）
  業績  EDINET（fetch_edinet.py。有価証券報告書は最新と2年前、半期報告書は直近の2冊。読んだものは保存して使い回す）

使い方:
    python scripts/build_breakout.py
"""
import json
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NAV, latest, load  # noqa: E402
import fetch_edinet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEEKLY = DATA / "weekly_2y.pkl"
RECENT_DAYS = 5                       # 直近何営業日の新高値を拾うか
PERIODS = (("半年", 182), ("1年", 365), ("2年", 730))
MIN_DAYS = 60                         # 上場から日が浅すぎる銘柄（新規上場の直後）は除く
BOX_MAX_RANGE, BOX_MIN_DAYS = 0.12, 20
VOL_SURGE = 2.0
Q_OP, Q_SALES = 20.0, 10.0            # ③ 営業利益・売上の前年同期比（%）


# ===== 株価 =====
def weekly_prices(codes: list) -> dict:
    """週足2年。その日のうちに取ったものがあれば使い回す。"""
    if WEEKLY.exists() and date.fromtimestamp(WEEKLY.stat().st_mtime) == date.today():
        return pd.read_pickle(WEEKLY)
    import yfinance as yf
    out, t0 = {}, time.time()
    for i in range(0, len(codes), 200):
        ch = codes[i:i + 200]
        try:
            d = yf.download([f"{c}.T" for c in ch], period="2y", interval="1wk", group_by="ticker",
                            auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print(f"  週足 {i}〜 取得失敗: {type(e).__name__}", flush=True)
            continue
        for c in ch:
            try:
                s = d[f"{c}.T"].dropna(how="all")
            except KeyError:
                continue
            if len(s):
                out[c] = s[["Open", "High", "Low", "Close", "Volume"]]
    print(f"  週足2年 {len(out)}銘柄  {time.time() - t0:.0f}秒", flush=True)
    pd.to_pickle(out, WEEKLY)
    return out


def clean(d: pd.DataFrame, limit: float) -> pd.DataFrame:
    """壊れた値（1本で前の終値の limit 倍を超える高値、10円未満）を除く。yfinance には時々混ざる。"""
    d = d.dropna(subset=["High", "Low", "Close"])
    d = d[(d["Close"] >= 10) & (d["Low"] > 0)]
    prev = d["Close"].shift()
    ok = ~((d["High"] > prev * limit) | (d["Low"] < prev / limit))
    return d[ok.fillna(True)]


def detect(code: str, day: pd.DataFrame, wk: pd.DataFrame):
    """直近5営業日の新高値。返り値は判定の dict（新高値でなければ None）。"""
    day = clean(day, 1.6)
    if len(day) < MIN_DAYS:
        return None
    d0 = day.index[0]
    old = clean(wk, 2.5) if wk is not None else pd.DataFrame(columns=day.columns)
    old = old[old.index + pd.Timedelta(days=4) < d0]          # 日足と重ならない週だけ
    hist_start = old.index[0] if len(old) else d0
    hits, best_i = {}, None
    n = len(day)
    for i in range(max(MIN_DAYS, n - RECENT_DAYS), n):
        t = day.index[i]
        hi = float(day["High"].iloc[i])
        for name, days in PERIODS:
            start = t - pd.Timedelta(days=days)
            prior = day["High"].iloc[:i][day.index[:i] >= start]
            prior_w = old["High"][old.index >= start]
            m = max(prior.max() if len(prior) else -1, prior_w.max() if len(prior_w) else -1)
            if m <= 0:
                continue
            short = hist_start > start + pd.Timedelta(days=14)      # この期間ぶんの株価が無い（上場が新しい）
            if hi > m:
                hits[name] = {"日": str(t.date()), "前の最高値": round(float(m), 1), "上場来": bool(short)}
                best_i = i
    if not hits:
        return None
    i = best_i
    t = day.index[i]
    # 出来高: その日 ÷ 前50営業日の平均
    vol = day["Volume"].iloc[max(0, i - 50):i]
    vr = float(day["Volume"].iloc[i] / vol.mean()) if len(vol) >= 20 and vol.mean() > 0 else None
    # ボックス: 新高値の日の前で、幅12%以内（BOX_MAX_RANGE）に収まっていた最長の期間（20営業日以上）
    box = None
    for L in range(BOX_MIN_DAYS, i + 1):
        w = day.iloc[i - L:i]
        rng = 1 - w["Low"].min() / w["High"].max()
        if rng > BOX_MAX_RANGE:
            break
        box = {"日数": L, "幅": round(rng * 100, 1), "上": round(float(w["High"].max()), 1),
               "下": round(float(w["Low"].min()), 1), "始": str(w.index[0].date())}
    cup = cup_shape(pd.concat([old, day.resample("W-MON", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()]), t)
    return {"hits": hits, "i": i, "日": str(t.date()), "高値": round(float(day["High"].iloc[i]), 1),
            "出来高倍": round(vr, 1) if vr else None, "box": box, "cup": cup}


def cup_shape(w: pd.DataFrame, t: pd.Timestamp):
    """カップ（と取っ手）の目安。w は週足（古い順）、t は新高値の日。"""
    w = w[~w.index.duplicated(keep="last")].sort_index()
    w = w[w.index + pd.Timedelta(days=6) < t]                 # 新高値の週より前
    if len(w) < 12:
        return None
    look = w.iloc[-52:]
    seg = look.iloc[:-7] if len(look) > 7 else None
    if seg is None or not len(seg):
        return None
    a_pos = int(np.argmax(seg["High"].values))
    A = float(seg["High"].iloc[a_pos])
    if A < look["High"].max() * 0.97:                          # A が土台の天井（もっと高い山が後にある形は除く）
        return None
    after = look.iloc[a_pos + 1:]
    if len(after) < 7:
        return None
    bottom = float(after["Low"].min())
    depth = 1 - bottom / A
    if not (0.12 <= depth <= 0.50):
        return None
    lower = int((after["Close"] < A - depth * A / 2).sum())    # カップの下半分にいた週の数（U字かどうか）
    if lower < 3:
        return None
    res = {"深さ": round(depth * 100), "週": len(after) + 1, "取っ手": False, "山": round(A, 1),
           "山の日": str(look.index[a_pos].date())}
    tail = after.iloc[-5:]
    b_pos = int(np.argmax(tail["High"].values))
    B = float(tail["High"].iloc[b_pos])
    if B >= A * 0.85 and b_pos < len(tail) - 1:
        pull = 1 - float(tail["Low"].iloc[b_pos + 1:].min()) / B
        if 0.03 <= pull <= 0.15:
            res.update({"取っ手": True, "押し": round(pull * 100)})
    return res


# ===== 業績（EDINET） =====
def fy_key(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def growth(cur, prev):
    if cur is None or prev is None:
        return None
    if prev > 0:
        return (cur / prev - 1) * 100
    return None


def halves(fy: dict, half: dict) -> list:
    """[(期の名前, 売上, 前年同期の売上, 営業利益, 前年同期の営業利益), ...]（古い順）。
    fy: {"売上": {期: 値}, "営業利益": {期: 値}}、half: {期: {"売上": (今, 前), "営業利益": (今, 前)}}
    上期は半期報告書の値、下期は 通期 − 上期。"""
    out = []
    for k in sorted(half):
        h = half[k]
        prev_k = fy_key(pd.Timestamp(k + "-01") - pd.DateOffset(years=1))
        s, sp = h.get("売上", (None, None))
        o, op = h.get("営業利益", (None, None))
        out.append((k, "上期", s, sp, o, op))
        # 下期: 通期（k）− 上期（k）、前年: 通期（k-1）− 上期（k-1）
        fs, fo = fy["売上"].get(k), fy["営業利益"].get(k)
        fsp, fop = fy["売上"].get(prev_k), fy["営業利益"].get(prev_k)
        if None not in (fs, s, fsp, sp):
            o2 = fo - o if None not in (fo, o) else None
            op2 = fop - op if None not in (fop, op) else None
            out.append((k, "下期", fs - s, fsp - sp, o2, op2))
    return out


def half_label(k: str, part: str) -> str:
    """期末 k（YYYY-MM）の上期・下期を「2026年4〜9月」のように。"""
    nxt = pd.Timestamp(k + "-01") + pd.DateOffset(months=1)          # 期末の翌月の1日（月末の計算のずれを避ける）
    if part == "上期":
        s, e = nxt - pd.DateOffset(months=12), nxt - pd.DateOffset(months=6, days=1)
    else:
        s, e = nxt - pd.DateOffset(months=6), nxt - pd.DateOffset(days=1)
    return f"{s.year}年{s.month}〜{e.month}月" if s.year == e.year else f"{s.year}年{s.month}月〜{e.year}年{e.month}月"


def judge_half(row):
    """1つの半期が③を満たすか（営業利益 +20%以上・売上 +10%以上。前年が赤字で黒字化なら利益は満たす）。"""
    _, _, s, sp, o, op = row
    if o is None or op is None:                 # 営業利益の無い会社（銀行・保険など）は判定しない
        return None, growth(s, sp), None, False
    gs, go = growth(s, sp), growth(o, op)
    turned = o is not None and op is not None and op <= 0 < o
    ok = gs is not None and gs >= Q_SALES and ((go is not None and go >= Q_OP) or turned)
    return ok, gs, go, turned


def fundamentals(codes: list, ends: pd.Series) -> dict:
    """銘柄ごとの ①〜④ の材料。"""
    key = fetch_edinet.api_key()
    if not key:
        print("  [!] EDINET のAPIキーが無いので、業績は空欄にします", flush=True)
        return {}
    has_fy = {c: ends[c] for c in codes if c in ends.index}
    fy_raw = fetch_edinet.ten_years(has_fy, backs=(2,)) if has_fy else {}
    half_raw = fetch_edinet.half_years(codes, key)
    out = {}
    for c in codes:
        f = fy_raw.get(c) or {"売上": {}, "営業利益": {}}
        S, O = f.get("売上", {}), f.get("営業利益", {})
        ks = sorted(set(S) & set(O))
        rec = {}
        # ② 直近の通期の営業利益の伸び（と、その前の年）
        if len(ks) >= 2:
            rec["通期"] = ks[-1]
            rec["営業利益"] = [round(O[k] / 1e8, 1) for k in ks[-4:]]
            rec["売上"] = [round(S[k] / 1e8, 1) for k in ks[-4:]]
            rec["②"] = growth(O[ks[-1]], O[ks[-2]])
            rec["②前"] = growth(O[ks[-2]], O[ks[-3]]) if len(ks) >= 3 else None
            # ④ 営業利益率
            m1, m0 = O[ks[-1]] / S[ks[-1]] * 100 if S[ks[-1]] else None, O[ks[-2]] / S[ks[-2]] * 100 if S[ks[-2]] else None
            rec["利益率"] = [round(m0, 1) if m0 is not None else None, round(m1, 1) if m1 is not None else None]
            rec["④"] = bool(m1 is not None and m0 is not None and m1 > m0 and S[ks[-1]] > S[ks[-2]])
        # ① 過去3年の営業利益の伸び（年率）
        o_ks = sorted(O)
        if len(o_ks) >= 4 and O[o_ks[-4]] > 0 and O[o_ks[-1]] > 0:
            rec["①"] = ((O[o_ks[-1]] / O[o_ks[-4]]) ** (1 / 3) - 1) * 100
        # ③ 直近2つの半期
        hv = halves({"売上": S, "営業利益": O}, half_raw.get(c, {}))
        hv = [h for h in hv if h[2] is not None and h[3] is not None]
        if hv:
            last = hv[-2:]
            res = [judge_half(h) for h in last]
            rec["半期"] = [{"期": half_label(h[0], h[1]), "売上": round(h[2] / 1e8, 1),
                            "売上伸び": None if r[1] is None else round(r[1], 1),
                            "営業利益": None if h[4] is None else round(h[4] / 1e8, 1),
                            "利益伸び": None if r[2] is None else round(r[2], 1),
                            "黒字化": r[3], "満たす": r[0]} for h, r in zip(last, res)]
            ok = [r[0] for r in res]
            if ok[-1] is None:
                rec["③"] = None
            else:
                rec["③"] = "◎" if len(ok) == 2 and all(ok) else ("○" if ok[-1] else "×")
        out[c] = rec
    return out


def grade2(v):
    if v is None:
        return None
    return "◎" if v >= 30 else "○" if v >= 20 else "△" if v >= 10 else "×"


def grade1(v):
    if v is None:
        return None
    return "◎" if v >= 10 else "○" if v >= 5 else "×"


# ===== ページ =====
def build(out_dir: Path) -> dict:
    df, asof = load()
    info = df.set_index("code")
    daily = pd.read_pickle(latest("prices_*.pkl"))
    wk = weekly_prices(sorted(daily))
    found = {}
    for c, d in daily.items():
        try:
            r = detect(c, d, wk.get(c))
        except Exception as e:                                  # 1銘柄の不具合でページ全体を止めない
            print(f"  [!] {c} の判定で失敗: {type(e).__name__}: {e}", flush=True)
            continue
        if r:
            found[c] = r
    n_all = {name: sum(name in r["hits"] for r in found.values()) for name, _ in PERIODS}
    print(f"新高値（直近{RECENT_DAYS}営業日）: 半年 {n_all['半年']}・1年 {n_all['1年']}・2年 {n_all['2年']}銘柄", flush=True)

    st = pd.read_csv(DATA / "statements.csv", dtype={"code": str})
    st = st[st["error"].fillna("") == ""]
    ends = st.sort_values("決算期").groupby("code").tail(1).set_index("code")["決算期"]
    fun = fundamentals(sorted(found), ends)

    rows = []
    for c, r in found.items():
        x = info.loc[c] if c in info.index else None
        if x is None:
            continue
        d = clean(daily[c], 1.6)
        f = fun.get(c, {})
        price = float(x["株価"])
        val = (d["Close"] * d["Volume"]).iloc[-20:].mean() / 1e8
        # グラフ: 週足2年の終値（日足6か月の分は日足から週ごとに）
        w = pd.concat([clean(wk[c], 2.5) if c in wk else pd.DataFrame(), d.resample("W-MON", label="left", closed="left")
                       .agg({"High": "max", "Low": "min", "Close": "last"}).dropna()])
        w = w[~w.index.duplicated(keep="last")].sort_index()
        w = w[w.index >= w.index[-1] - pd.Timedelta(days=735)]
        top = max(r["hits"].items(), key=lambda kv: dict(PERIODS)[kv[0]])
        rows.append({
            "銘柄": f"{c} {x['name']}",
            "期間": {k: (v["上場来"] and "上場来") or True for k, v in r["hits"].items()},
            "日": r["日"][5:].replace("-", "/"),
            "前の最高値": top[1]["前の最高値"],
            "株価": round(price, 1),
            "高値から": round((price / r["高値"] - 1) * 100, 1),
            "出来高倍": r["出来高倍"],
            "ボックス": r["box"],
            "カップ": r["cup"],
            "③": f.get("③"), "半期": f.get("半期"),
            "②": None if f.get("②") is None else round(f["②"], 1), "②前": None if f.get("②前") is None else round(f["②前"], 1),
            "②評価": grade2(f.get("②")),
            "①": None if f.get("①") is None else round(f["①"], 1), "①評価": grade1(f.get("①")),
            "④": f.get("④"), "利益率": f.get("利益率"),
            "通期": f.get("通期"), "営業利益": f.get("営業利益"), "売上": f.get("売上"),
            "時価総額": None if pd.isna(x["時価総額億"]) else round(float(x["時価総額億"])),
            "売買代金": round(float(val), 2) if pd.notna(val) else None,
            "業種": x.get("sector") if isinstance(x.get("sector"), str) else None,
            "週": [[str(t.date()), round(float(v), 1)] for t, v in w["Close"].items()],
            "最高値日": r["日"],
        })
    order3 = {"◎": 0, "○": 1, "×": 2, None: 3}
    rows.sort(key=lambda z: (order3[z["③"]], -(z["②"] if z["②"] is not None else -1e9), -(len(z["期間"]))))
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": asof, "count": len(rows),
               "counts": n_all, "rows": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "breakout.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (out_dir / "breakout.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    return (Path(__file__).resolve().parent / "breakout_template.html").read_text(encoding="utf-8") \
        .replace("__NAV__", '<div class="nav">' + "".join(f'<a href="{h}">{t}</a>' for h, t in NAV if h != "breakout.html") + "</div>") \
        .replace("__DATA__", json.dumps(p, ensure_ascii=False))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(out)
    print(f"作成: {out / 'breakout.html'}  {p['count']}銘柄")
