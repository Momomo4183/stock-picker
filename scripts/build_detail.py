# -*- coding: utf-8 -*-
"""PER検索の結果に出す、銘柄ごとの「4つのスクリーニングの全要素」（docs/detail/コード先頭2文字.json）を作る。

2026-10-18 ご本人の依頼: 検索結果に、これまでの4条件（高配当株 15指標・グロース株・連続増配株・
期待値投資）で使っている要素を、点数も含めてすべて出したい。スクリーニングで絞った銘柄を、
最後に買うかどうか決めるとき、また売りの判断の目安として、検索して全要素で確かめるため。

各ページと同じ判定を、ページの対象に入っていない銘柄も含めて全銘柄で出す:
  高配当株 15指標  build_check15.judge をそのまま使う。配当の伸び・減配・利回りの前年比は、
                   ページは日足7年、ここは配当履歴（actions）と月末の株価で出すので、少しずれることがある
  グロース株       build_growth と同じ計算（成長率は yfinance の決算書4〜5期）
  連続増配株       build_renzoku の stage2・adjust と同じ。第1段階の各条件も個別に出す
  期待値投資       売上は有価証券報告書。10期ずっと増収している銘柄だけ、営業利益10期と11期目の売上を取りに行く
ページの判定と同じ数字にするため、しきい値は各ページのモジュールから読む。

ファイルは銘柄コードの先頭2文字ごとにまとめる（3,600銘柄を1ファイルずつにすると更新のたびに git が重い）。

使い方（build_per_data.py のあとに実行する。PERの月次データと報告書の保存分を使う）:
    python scripts/build_detail.py
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load  # noqa: E402
import build_check15 as c15  # noqa: E402
import build_growth as gr  # noqa: E402
import build_renzoku as rz  # noqa: E402
import build_kitaichi as kt  # noqa: E402
import fetch_edinet  # noqa: E402
import fetch_statements  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "detail"


def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def r1(v, d=1):
    v = num(v)
    return None if v is None else round(v, d)


def dividend_facts(dv: dict, price_now, per_csv: Path) -> dict:
    """15指標の「配当」「急上昇」の材料（配当の伸び・減配・利回りの前年比）。"""
    out = {}
    if not dv:
        return out
    s = pd.Series(dv)
    s.index = pd.to_datetime(s.index)
    today = pd.Timestamp.today().normalize()
    yearly = s.groupby(s.index.year).sum()
    first = s.index.min().year
    yearly = yearly[(yearly.index > first) & (yearly.index < today.year)].tail(6)
    if len(yearly) >= 3:
        v = yearly.values
        out["減配"] = int(sum(v[i] < v[i - 1] * 0.97 for i in range(1, len(v))))
        if v[0] > 0:
            out["配当の伸び"] = float(v[-1] / v[0])
    ttm_now = s[s.index > today - pd.Timedelta(days=365)].sum()
    ttm_ago = s[(s.index > today - pd.Timedelta(days=730)) & (s.index <= today - pd.Timedelta(days=365))].sum()
    if per_csv.exists() and price_now and ttm_now > 0 and ttm_ago > 0:
        m = pd.read_csv(per_csv)
        m = m[m["年月"] <= (today - pd.DateOffset(years=1)).strftime("%Y-%m")]
        if len(m):
            p_ago = float(m["株価"].iloc[-1])
            out["利回り前年比"] = float((ttm_now / price_now) / (ttm_ago / p_ago))
    return out


def growth_part(r, g) -> dict:
    """グロース株の候補のページと同じ計算。"""
    out = {"対象": bool(num(r["時価総額億"]) is not None and r["時価総額億"] >= gr.MIN_CAP
                        and num(r.get("売買代金")) is not None and r["売買代金"] >= gr.MIN_DAI),
           "時価総額億": r1(r["時価総額億"], 0), "売買代金万": r1((num(r.get("売買代金")) or 0) / 1e4, 0)}
    if g is None or len(g["売上"].dropna()) < 3:
        out["判定"] = "決算書のデータ不足"
        return out
    rev, op, ni = g["売上"].dropna(), g["営業利益"].dropna(), g["純利益"].dropna()
    g_rev, g_op, g_ni = gr.cagr(rev), gr.cagr(op), gr.cagr(ni)
    last_rev = float(rev.iloc[-1] / rev.iloc[-2] - 1) if rev.iloc[-2] > 0 else None
    per = num(r["PER"])
    g_peg = min(g_ni, g_op, gr.PEG_GROWTH_CAP) if g_ni and g_ni > 0 and g_op else None
    peg = per / (g_peg * 100) if per and g_peg else None
    margin_now = op.iloc[-1] / rev.iloc[-1] if len(op) and rev.iloc[-1] else None
    margin_old = op.iloc[0] / rev.iloc[0] if len(op) and rev.iloc[0] else None
    eq = num(g["純資産"].dropna().iloc[-1]) if g["純資産"].notna().any() else None
    net = num(ni.iloc[-1]) if len(ni) else None
    cf = g["営業CF"].dropna()
    ok_rev = g_rev is not None and g_rev >= gr.MIN_GROWTH
    ok_op = g_op is not None and g_op >= gr.MIN_GROWTH
    ok_last = last_rev is not None and last_rev > 0
    out.update({
        "売上成長": [r1(g_rev * 100) if g_rev is not None else None, ok_rev],
        "営業利益成長": [r1(g_op * 100) if g_op is not None else None, ok_op],
        "直近売上": [r1(last_rev * 100) if last_rev is not None else None, ok_last],
        "グロース": bool(ok_rev and ok_op and ok_last),
        "PEG": ([r1(peg, 2), "要確認"] if peg is not None and per < gr.MIN_PER_FOR_PEG else r1(peg, 2)),
        "利益成長": r1(g_ni * 100) if g_ni is not None else None,
        "増収": f"{int((rev.diff().dropna() > 0).sum())}/{len(rev) - 1}",
        "営業利益率": r1(margin_now * 100) if margin_now is not None else None,
        "利益率の改善": r1((margin_now - margin_old) * 100) if margin_now is not None and margin_old is not None else None,
        "ROE": r1(net / eq * 100) if net is not None and eq and eq > 0 else None,
        "営業CF": None if len(cf) < 2 else "全期プラス" if (cf > 0).all() else f"マイナス{int((cf <= 0).sum())}期",
        "PER": r1(per), "PSR": r1(r["時価総額億"] * 1e8 / rev.iloc[-1], 2) if rev.iloc[-1] > 0 else None,
        "PBR": r1(r["PBR"], 2), "6か月騰落": r1((num(r.get("6か月騰落")) or 0) * 100) if num(r.get("6か月騰落")) is not None else None,
        "荒さ": r1(r.get("荒さ"), 0),
    })
    return out


def renzoku_part(r, lat, rec, act, cover) -> dict:
    s = rz.STAGE1
    roe = roa = eqr = None
    if lat is not None:
        roe = num(lat["純利益"]) / num(lat["純資産"]) * 100 if num(lat["純資産"]) and num(lat["純利益"]) is not None else None
        roa = num(lat["純利益"]) / num(lat["総資産"]) * 100 if num(lat["総資産"]) and num(lat["純利益"]) is not None else None
        eqr = num(lat["純資産"]) / num(lat["総資産"]) * 100 if num(lat["総資産"]) and num(lat["純資産"]) is not None else None
    per, pbr, y, cap = num(r["PER"]), num(r["PBR"]), num(r["配当利回り%"]), num(r["時価総額億"])
    st1 = [["PER", r1(per), f"{s['PER']}倍以下", per is not None and 0 < per <= s["PER"]],
           ["PBR", r1(pbr, 2), f"{s['PBR']}倍以下", pbr is not None and pbr <= s["PBR"]],
           ["ROE", r1(roe), f"{s['ROE']}%以上", roe is not None and roe >= s["ROE"]],
           ["ROA", r1(roa), f"{s['ROA']}%以上", roa is not None and roa >= s["ROA"]],
           ["配当利回り", r1(y, 2), f"{s['配当利回り']}%以上", y is not None and y >= s["配当利回り"]],
           ["自己資本比率", r1(eqr), f"{s['自己資本比率']}%以上", eqr is not None and eqr >= s["自己資本比率"]],
           ["時価総額", r1(cap, 0), f"{s['時価総額']}億円以上", cap is not None and cap >= s["時価総額"]]]
    a = rz.adjust(rec, act) if rec else {}
    ok2, why, x = rz.stage2(a)
    eps, bps, dps = a.get("EPS", []), a.get("BPS", []), a.get("DPS", [])
    full = len(a.get("fy", [])) >= 10
    st2 = [["EPSが赤字の期なし", f"最低 {r1(min(eps), 1)}" if eps else None, full and min(eps) > 0 if eps else False],
           ["EPSが9期前の2倍以上", f"{r1(x.get('EPS倍'), 2)}倍" if x.get("EPS倍") else None, bool(x.get("EPS倍") and x["EPS倍"] >= 2 and full)],
           ["BPSが10期ともプラス", f"最低 {r1(min(bps), 1)}" if bps else None, full and min(bps) > 0 if bps else False],
           ["減配は1回まで", f"{x['減配']}回" if x.get("減配") is not None else None, x.get("減配") is not None and x["減配"] <= 1 and full],
           ["無配の期なし", "なし" if dps and all(v and v > 0 for v in dps) else "あり・データ欠け", bool(dps and all(v and v > 0 for v in dps) and full)]]
    words = (rec or {}).get("words", {})
    doe, up, every = bool(words.get("DOE")), (x.get("BPS倍") or 0) > 1, bool(x.get("BPS毎期増"))
    bd = (4, "BPS毎期増×DOE") if every and doe else (3, "BPS伸び×DOE") if up and doe else \
        (2, "BPS毎期増") if every else (1, "BPS伸び") if up else (1, "DOEの記載") if doe else (0, "なし")
    payout = num(r.get("配当性向%"))
    payout = payout if payout and payout > 0 else None
    cv = cover
    pts = [["累進配当の記載", "あり" if words.get("累進配当") else "なし", 1 if words.get("累進配当") else 0],
           ["BPSとDOEの組み合わせ", bd[1], bd[0]],
           ["連続増配5期以上", f"{x.get('連続増配')}期" if x.get("連続増配") is not None else "–", 1 if (x.get("連続増配") or 0) >= 5 else 0],
           ["配当性向50%以下", f"{round(payout)}%" if payout else "–", 1 if payout is not None and payout <= 50 else 0],
           ["営業CFで配当をまかなえる", f"{r1(cv)}倍" if cv is not None else "データなし", 1 if cv is not None and cv > 1 else 0]]
    bv, dr = num(r.get("bookValue")), num(r.get("dividendRate"))
    return {"第1段階": st1, "第1段階通過": all(c[3] for c in st1), "第2段階": st2, "第2段階通過": bool(ok2),
            "理由": "・".join(why), "加点": [p for p in pts], "合計": sum(p[2] for p in pts),
            "連続増配": x.get("連続増配"), "配当10期": [r1(v, 2) for v in dps], "配当倍": r1(x.get("配当倍"), 2),
            "BPS10期": [r1(v, 1) for v in bps], "EPS10期": [r1(v, 1) for v in eps],
            "期": f"{a['fy'][0]}〜{a['fy'][-1]}" if a.get("fy") else None,
            "DOE": r1(dr / bv * 100) if bv and dr else None, "方針": (rec or {}).get("policy") or None}


def kitaichi_part(r, rec) -> dict:
    y, pr = num(r["配当利回り%"]), num(r.get("配当性向%"))
    out = {"配当利回り": [r1(y, 2), y is not None and y >= kt.MIN_YIELD],
           "配当性向": [round(pr) if pr is not None else None, pr is not None and 0 < pr <= kt.MAX_PAYOUT]}
    sales = rec.get("売上", {}) if rec else {}
    v = [sales[k] for k in sorted(sales)]
    streak = kt.sales_streak(sales) if sales else 0
    out["売上"] = [streak, len(v) >= 11 and streak >= 10, [r1(x / 1e8, 1) for x in v[-11:]]]
    op = rec.get("営業利益", {}) if rec else {}
    if len(op) >= 10:
        ok, opv, cuts, ratio = kt.op_trend(op)
        out["営業利益"] = [r1(ratio, 2), ok, [r1(x / 1e8, 1) for x in opv], cuts]
    else:
        # 売上が10期伸びていない銘柄は取りに行かない。取りに行っても10期そろわない会社もある
        # （例: KDDI は IFRS に移る前の営業利益が読めず8期分）→ 判定しない（ページにも載らない）
        out["営業利益"] = [None, None, [], None]
    out["営業利益期数"] = len(op)
    out["通過"] = bool(out["配当利回り"][1] and out["配当性向"][1] and out["売上"][1] and out["営業利益"][1])
    return out


def build() -> int:
    df, asof = load()
    df = df.merge(gr.market_extras(), on="code", how="left")
    have = {p.stem for p in (DOCS / "per").glob("*.csv")}
    ends = kt.fy_ends()
    codes = [c for c in df["code"] if c in ends.index]
    print(f"全要素を出す銘柄 {len(codes)}", flush=True)
    # 決算書（配当の支払額は 2026-10-18 に足した項目なので、それより前に取った分は取り直す）
    stm = fetch_statements.update(codes, since="2026-10-18")
    stm = stm[stm["error"].fillna("") == ""]
    by_code = {c: g.sort_values("決算期") for c, g in stm.groupby("code")}
    cover = {}
    for c, g in by_code.items():
        g = g.dropna(subset=["営業CF", "配当支払"])
        g = g[g["配当支払"] < 0]
        if len(g) >= 3:
            cover[c] = float((g["営業CF"] / -g["配当支払"]).min())
    raw = fetch_edinet.ten_years({c: ends[c] for c in codes})
    # 期待値投資: 売上が10期ずっと伸びている銘柄だけ、営業利益10期と11期目の売上を取りに行く
    more = [c for c, r in raw.items() if len(r["売上"]) >= 10 and kt.sales_streak(r["売上"]) >= 9]
    print(f"  売上が10期ずっと伸びている {len(more)}銘柄は、営業利益も取ります", flush=True)
    raw2 = fetch_edinet.ten_years({c: ends[c] for c in more}, backs=(2, 4, 5, 6, 8))
    for c, r in raw2.items():
        raw[c] = r
    act = rz.actions_for(codes, max_age=30)
    empty = pd.DataFrame(columns=["決算期"] + [f[0] for f in fetch_statements.FIELDS])
    # 15指標のページに載っている銘柄は、ページと同じ配当の材料（日足7年から出したもの）を使う
    page15 = {}
    f15 = DOCS / "check15.json"
    if f15.exists():
        for x in json.loads(f15.read_text(encoding="utf-8"))["rows"]:
            dv = {}
            if x.get("配当"):
                dv["配当の伸び"], dv["減配"] = 1 + x["配当"][0] / 100, x["配当"][2]
            if x.get("急上昇"):
                dv["利回り前年比"] = x["急上昇"][0]
            page15[x["銘柄"].split(" ")[0]] = dv
    shards = {}
    for _, r in df[df["code"].isin(codes)].iterrows():
        c = r["code"]
        try:
            g = by_code.get(c)
            dv = page15[c] if c in page15 else \
                dividend_facts(act.get(c, {}).get("dividends", {}), num(r["株価"]), DOCS / "per" / f"{c}.csv")
            j = c15.judge(r, g if g is not None else empty, dv)
            scored = [j[k][1] for k in c15.SCORED if k in j and j[k][1] != "n"]
            lat = g.iloc[-1] if g is not None and len(g) else None
            rec = {
                "名前": r["name"], "業種": r.get("sector") if isinstance(r.get("sector"), str) else None,
                "株価": r1(r["株価"]), "高配当": {
                    "対象": bool(num(r["配当利回り%"]) is not None and r["配当利回り%"] >= c15.MIN_YIELD
                                and num(r["時価総額億"]) is not None and r["時価総額億"] >= c15.MIN_CAP),
                    "配当利回り": r1(r["配当利回り%"], 2), "時価総額億": r1(r["時価総額億"], 0),
                    "合格": [sum(s in ("p", "g") for s in scored), len(scored)], "指標": j},
                "グロース": growth_part(r, g),
                "連続増配": renzoku_part(r, lat, raw.get(c), act.get(c, {}), cover.get(c)),
                "期待値": kitaichi_part(r, raw.get(c)),
            }
            rec["期待値"]["PERあり"] = c in have
            shards.setdefault(c[:2], {})[c] = rec
        except Exception as e:
            print(f"  [!] {c} を飛ばしました（{type(e).__name__}: {e}）", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for k, v in shards.items():
        (OUT / f"{k}.json").write_text(json.dumps({"asof": asof["株価"], "stocks": v}, ensure_ascii=False,
                                                  separators=(",", ":")), encoding="utf-8")
    n = sum(len(v) for v in shards.values())
    print(f"作成: {OUT}  {n}銘柄・{len(shards)}ファイル", flush=True)
    return n


if __name__ == "__main__":
    build()
