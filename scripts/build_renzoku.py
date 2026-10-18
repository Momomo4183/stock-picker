# -*- coding: utf-8 -*-
"""連続増配株のページ（docs/renzoku.html）を作る。

2026-10-18 ご本人が示した条件:
  第1段階（今の状態・必須）  PER12倍以下・PBR1.3倍以下・ROE7%以上・ROA3%以上・
                             配当利回り3%以上・自己資本比率35%以上・時価総額100億円以上
  第2段階（過去10期・必須）  EPS 赤字が1期も無い・9期前の2倍以上
                             BPS 10期ともプラス
                             配当 10期で減配は1回まで・無配の期が無い
  加点（2026-10-18 ご本人の指定）  累進配当の記載 +1 に、BPS と DOE の組み合わせの点を足す（最大5点）
        BPS・DOE の点は、当てはまるもののうち一番高いもの（重ねて足さない）:
          DOE の記載だけ +1 ／ BPS が9期前より伸びた +1 ／ BPS が毎期増えた +2 ／
          BPS が伸びた かつ DOE +3 ／ BPS が毎期増えた かつ DOE +4

データ:
  第1段階 … ほかのページと同じ（株価・1株あたりの値・yfinance の決算書）。
            ROE・ROA・自己資本比率は直近の決算期の 純利益÷純資産・純利益÷総資産・純資産÷総資産
  第2段階 … EDINET の有価証券報告書（最新と5年前）の「主要な経営指標等の推移」から10期分
  累進配当・DOE … 最新の有価証券報告書の文章（配当政策など）に言葉が出てくるか。
            決算説明資料・中期経営計画には書いてあっても、報告書に無ければ拾えない

株式分割の扱い:
  1株あたりの値は、報告書によって分割後に直してあったり、当時のままだったりする。
  （三菱商事は2024年の1:3分割で、最新の報告書では2022年3月期の配当も150円→50円に直してある）。
  EPS・BPS は「当時のまま」と「報告書を出した時点で直してある」の2通りを考え、
  BPS が前後の期と一番なめらかにつながるほうを選び、同じ期の EPS にも同じ直し方を使う
  （BPS は1年で何倍にもならないため。分割の履歴は yfinance、効力発生日に直して使う）。
  配当は、報告書だと当時の実額の年と直した年が混ざり、分割の年は中間と期末で基準も違うので、
  yfinance の配当履歴（今の株数の基準）を権利落ち日で期ごとに合計して使う。
  yfinance に記録が無い期だけ報告書の値を使う。

使い方:
    python scripts/build_renzoku.py
"""
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load  # noqa: E402
import fetch_edinet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STAGE1 = {"PER": 12, "PBR": 1.3, "ROE": 7, "ROA": 3, "配当利回り": 3, "自己資本比率": 35, "時価総額": 100}
ACTIONS = ROOT / "data" / "actions.json"
EFFECTIVE = 4      # yfinance の分割日は権利落ち日。効力発生日（数日後）に直す


def actions_for(codes: list) -> dict:
    """株式分割と配当の履歴（yfinance、分割調整済み）。7日間使い回す。"""
    import yfinance as yf
    cache = json.loads(ACTIONS.read_text(encoding="utf-8")) if ACTIONS.exists() else {}
    limit = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    for c in codes:
        if c in cache and cache[c]["取得日"] >= limit:
            continue
        try:
            t = yf.Ticker(f"{c}.T")
            sp, dv = t.splits, t.dividends
            cache[c] = {"取得日": datetime.now().strftime("%Y-%m-%d"),
                        "splits": {(d + timedelta(days=EFFECTIVE)).strftime("%Y-%m-%d"): float(r)
                                   for d, r in sp.items() if r and r > 0},
                        "dividends": {d.strftime("%Y-%m-%d"): float(v) for d, v in dv.items() if v > 0}}
        except Exception:
            continue
    ACTIONS.parent.mkdir(parents=True, exist_ok=True)
    ACTIONS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {c: cache.get(c, {"splits": {}, "dividends": {}}) for c in codes}


def factor(splits: dict, after: str) -> float:
    f = 1.0
    for d, r in splits.items():
        if d > after:
            f *= r
    return f


def adjust(rec: dict, act: dict) -> dict:
    """10期分の EPS・BPS・DPS を、今の株数の基準にそろえる。"""
    fys = sorted(set(rec["BPS"]) & set(rec["EPS"]))[-10:]
    if not fys:
        return {}
    splits = act.get("splits", {})
    ends = {fy: (pd.Timestamp(fy + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d") for fy in fys}
    n = len(fys)
    out = {"fy": fys, "EPS": [None] * n, "BPS": [None] * n, "DPS": [None] * n}

    def pick(v, raw, filed, nxt):
        """「当時のまま」と「提出時点で直してある」のうち、新しい期となめらかにつながるほう。"""
        if raw == filed or v is None or v <= 0 or not nxt:
            return filed
        return min((raw, filed), key=lambda c: abs(math.log(v / c / nxt)))

    for i in range(n - 1, -1, -1):
        fy = fys[i]
        raw = factor(splits, ends[fy])                                       # 当時のまま
        filed = factor(splits, rec["src"].get("BPS", {}).get(fy, ends[fy]))  # 提出時点で直してある
        b, e = rec["BPS"][fy], rec["EPS"][fy]
        f = pick(b, raw, filed, out["BPS"][i + 1] if i < n - 1 else None)
        out["BPS"][i], out["EPS"][i] = b / f, e / f                           # EPS は BPS と同じ直し方
    # 配当は yfinance の履歴（今の株数の基準に直してある）を、権利落ち日で期ごとに合計する。
    # 報告書の配当は、当時の実額のままの年と直してある年が混ざり、分割の年は中間と期末で基準が違うため。
    # yfinance に配当の記録が無い期だけ、報告書の値（分割を推定で直したもの）を使う
    dv = act.get("dividends", {})
    for i in range(n - 1, -1, -1):
        fy = fys[i]
        start = (pd.Timestamp(ends[fy]) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        y = sum(v for d, v in dv.items() if start < d <= ends[fy])
        if y > 0:
            out["DPS"][i] = y
            continue
        d = rec["DPS"].get(fy)
        if d is None or d <= 0:
            out["DPS"][i] = d if d is None else 0.0           # 報告書でも無配（または記載なし）
            continue
        raw = factor(splits, ends[fy])                        # 報告書には配当があるのに yfinance に無い期
        filed = factor(splits, rec["src"].get("DPS", {}).get(fy, ends[fy]))
        nd = next((out["DPS"][j] for j in range(i + 1, n) if out["DPS"][j]), None)
        out["DPS"][i] = d / pick(d, raw, filed, nd)
    return out


def stage1(df: pd.DataFrame) -> pd.DataFrame:
    st = pd.read_csv(ROOT / "data" / "statements.csv", dtype={"code": str})
    st = st[st["error"].fillna("") == ""]
    lat = st.sort_values("決算期").groupby("code").tail(1).set_index("code")
    d = df.set_index("code")
    d["ROE"] = lat["純利益"] / lat["純資産"] * 100
    d["ROA"] = lat["純利益"] / lat["総資産"] * 100
    d["自己資本比率"] = lat["純資産"] / lat["総資産"] * 100
    d["決算期"] = lat["決算期"]
    m = ((d["PER"] > 0) & (d["PER"] <= STAGE1["PER"]) & (d["PBR"] <= STAGE1["PBR"])
         & (d["ROE"] >= STAGE1["ROE"]) & (d["ROA"] >= STAGE1["ROA"])
         & (d["配当利回り%"] >= STAGE1["配当利回り"]) & (d["自己資本比率"] >= STAGE1["自己資本比率"])
         & (d["時価総額億"] >= STAGE1["時価総額"]) & d["決算期"].notna())
    return d[m.fillna(False)].reset_index()


def stage2(a: dict) -> tuple:
    """(通ったか, 落ちた理由のリスト, 指標)"""
    why, x = [], {}
    if not a or len(a["fy"]) < 10:
        return False, [f"10期分のデータなし（{len(a.get('fy', [])) if a else 0}期）"], x
    eps, bps, dps = a["EPS"], a["BPS"], a["DPS"]
    if min(eps) <= 0:
        why.append("EPSが赤字の期あり")
    x["EPS倍"] = eps[-1] / eps[0] if eps[0] > 0 else None
    if not x["EPS倍"] or x["EPS倍"] < 2:
        why.append("EPSが9期前の2倍未満")
    if min(bps) <= 0:
        why.append("BPSがマイナスの期あり")
    x["BPS倍"] = bps[-1] / bps[0] if bps[0] > 0 else None
    x["BPS毎期増"] = all(bps[i] > bps[i - 1] for i in range(1, 10))
    if any(v is None or v <= 0 for v in dps):
        why.append("無配の期あり（または配当のデータ欠け）")
        x["減配"] = None
    else:
        v = dps
        x["減配"] = sum(v[i] < v[i - 1] * 0.995 for i in range(1, len(v)))
        if x["減配"] > 1:
            why.append(f"減配{x['減配']}回")
        streak = 0
        for i in range(len(v) - 1, 0, -1):
            if v[i] > v[i - 1] * 1.001:
                streak += 1
            else:
                break
        x["連続増配"] = streak
        x["配当倍"] = dps[-1] / dps[0]
    return not why, why, x


def build(out_dir: Path) -> dict:
    df, asof = load()
    c1 = stage1(df)
    print(f"第1段階を通った銘柄 {len(c1)}", flush=True)
    raw = fetch_edinet.ten_years(dict(zip(c1["code"], c1["決算期"])))
    act = actions_for(c1["code"].tolist())
    rows = []
    for _, r in c1.iterrows():
        rec = raw.get(r["code"])
        a = adjust(rec, act.get(r["code"], {})) if rec else {}
        ok, why, x = stage2(a)
        words = (rec or {}).get("words", {})
        doe, up, every = bool(words.get("DOE")), (x.get("BPS倍") or 0) > 1, bool(x.get("BPS毎期増"))
        bd = (4, "BPS毎期増×DOE") if every and doe else (3, "BPS伸び×DOE") if up and doe else              (2, "BPS毎期増") if every else (1, "BPS伸び") if up else (1, "DOE") if doe else (0, "")
        pts = {"累進配当": 1 if words.get("累進配当") else 0, "BPS・DOE": bd[0], "組み合わせ": bd[1]}
        bv, dr = r.get("bookValue"), r.get("dividendRate")
        rows.append({
            "銘柄": f"{r['code']} {r['name']}",
            "通過": ok,
            "理由": "・".join(why),
            "加点": pts["累進配当"] + pts["BPS・DOE"],
            "内訳": pts,
            "株価": round(float(r["株価"]), 1),
            "配当利回り": round(float(r["配当利回り%"]), 2),
            "連続増配": x.get("連続増配"),
            "配当10期": [round(v, 2) if v is not None else None for v in a.get("DPS", [])],
            "配当倍": round(x["配当倍"], 2) if x.get("配当倍") else None,
            "減配": x.get("減配"),
            "EPS倍": round(x["EPS倍"], 2) if x.get("EPS倍") else None,
            "BPS10期": [round(v, 1) for v in a.get("BPS", [])],
            "BPS倍": round(x["BPS倍"], 2) if x.get("BPS倍") else None,
            "BPS毎期増": x.get("BPS毎期増"),
            "累進配当": bool(words.get("累進配当")),
            "DOE記載": bool(words.get("DOE")),
            "DOE": round(dr / bv * 100, 1) if pd.notna(bv) and bv and pd.notna(dr) else None,
            "PER": round(float(r["PER"]), 1),
            "PBR": round(float(r["PBR"]), 2),
            "ROE": round(float(r["ROE"]), 1),
            "ROA": round(float(r["ROA"]), 1),
            "自己資本比率": round(float(r["自己資本比率"]), 1),
            "時価総額": round(float(r["時価総額億"])),
            "業種": r.get("sector") if isinstance(r.get("sector"), str) else None,
            "期": f"{a['fy'][0]}〜{a['fy'][-1]}" if a.get("fy") else None,
            "方針": (rec or {}).get("policy") or None,
        })
    rows.sort(key=lambda x: (-x["通過"], -x["加点"], -(x["連続増配"] or 0), -x["配当利回り"]))
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": asof,
               "count": sum(x["通過"] for x in rows), "stage1": len(rows), "rows": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "renzoku.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "renzoku.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    data = json.dumps(p, ensure_ascii=False)
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>連続増配株</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 6px}
h1{margin:0;font-size:19px}
.meta{color:var(--sub);font-size:12px;margin-top:4px}
.nav{font-size:12.5px;margin-top:6px}.nav a{color:var(--accent);margin-right:14px}
section{padding:6px 14px 40px}
.desc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
.desc b{color:var(--ink)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
summary{color:var(--ink);font-weight:600;cursor:pointer}
dl{margin:8px 0 2px}dt{color:var(--ink);font-weight:600;margin-top:6px}dd{margin:0}
.bar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--sub);margin:8px 2px}
.bar label{display:flex;gap:5px;align-items:center;cursor:pointer}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:10em;max-width:11.5em}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.g{color:var(--good);font-weight:700}.w{color:var(--warn)}.s{color:var(--sub)}
.pt{font-weight:700;font-size:13.5px}
.mk{display:inline-block;font-size:11px;font-weight:700;border-radius:5px;padding:0 5px;margin-left:2px;background:var(--hi);color:var(--good);border:1px solid var(--line)}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
.more{font:inherit;font-size:11.5px;color:var(--accent);background:none;border:1px solid var(--line);border-radius:6px;padding:1px 7px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
tr.detail td{white-space:normal;text-align:left;font-size:12px;color:var(--sub);background:var(--hi);position:static}
tr.fail td{color:var(--sub)}
svg.sp{vertical-align:middle}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>連続増配株</h1><div class="meta" id="meta"></div>
<div class="nav"><a href="./">トップ</a><a href="check15.html">高配当株 15指標チェック</a><a href="growth.html">グロース株の候補</a><a href="common.html">3つに共通する銘柄</a></div></header>
<section>
<div class="desc"><b>第1段階（今の状態）</b>　PER12倍以下・PBR1.3倍以下・ROE7%以上・ROA3%以上・配当利回り3%以上・自己資本比率35%以上・時価総額100億円以上<br>
<b>第2段階（過去10期）</b>　EPSが赤字の期なし・9期前の2倍以上／BPSが10期ともプラス／配当は減配1回まで・無配なし<br>
両方を満たした銘柄を<b>加点</b>の多い順に並べています（累進配当+1に、BPSとDOEの組み合わせで最大+4）。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー、<b>方針</b>で有価証券報告書の配当方針。</div>
<details><summary>各列の見方</summary><dl>
<dt>加点</dt><dd>累進配当の記載 +1 に、BPSとDOEの組み合わせの点を足します（最大5点）。BPS・DOEの点は当てはまる中で一番高いもの：DOEの記載だけ +1、BPSが9期前より伸びた +1、BPSが毎期増えた +2、BPSが伸びた かつ DOE +3、BPSが毎期増えた かつ DOE +4。累進配当・DOEは最新の有価証券報告書の文章（配当政策など）に言葉があるかで判定。決算説明資料や中期経営計画にだけ書いてある場合は拾えません。</dd>
<dt>連続増配</dt><dd>直近の期から何期続けて増配しているか（有価証券報告書の1株あたり配当、株式分割は調整済み）。記念配当で増えた・減った期も、そのまま数えます。</dd>
<dt>配当（10期）</dt><dd>10期分の1株配当の推移と、10期前→直近の倍率、減配の回数。</dd>
<dt>EPS・BPS（10期）</dt><dd>9期前に対する倍率。BPSの「毎期」は10期続けて増えた印。</dd>
<dt>DOE</dt><dd>今の予想配当÷1株純資産（%）。「記載」はDOEを方針に使うと書いてある印。</dd>
<dt>ROE・ROA・自己資本比率</dt><dd>直近の決算期の値（純利益÷純資産、純利益÷総資産、純資産÷総資産）。</dd>
<dt>第2段階で落ちた銘柄</dt><dd>上のチェックを入れると、第1段階だけ通った銘柄も理由つきで灰色で表示します。</dd>
</dl></details>
<div class="bar"><span id="count"></span><label><input type="checkbox" id="showFail">第2段階で落ちた銘柄も表示</label></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const COLS = ["銘柄","加点","株価","配当利回り","連続増配","配当10期","EPS倍","BPS10期","DOE","PER","PBR","ROE","ROA","自己資本比率","時価総額","業種","方針"];
const HEAD = {"配当10期":"配当（10期）","EPS倍":"EPS（10期）","BPS10期":"BPS（10期）","配当利回り":"利回り%","自己資本比率":"自己資本比率%","ROE":"ROE%","ROA":"ROA%","DOE":"DOE%","時価総額":"時価総額億"};
const SORTKEY = {"配当10期":"配当倍","BPS10期":"BPS倍"};
let sortCol = null, sortAsc = false, open = new Set();
document.getElementById("meta").textContent = `株価 ${D.asof.株価} 時点 ／ 作成 ${D.generated}`;
function spark(v) {
  const xs = v.filter(x => x !== null && x !== undefined);
  if (xs.length < 2) return "";
  const lo = Math.min(...xs), hi = Math.max(...xs), w = 54, h = 16;
  const pts = v.map((x, i) => x === null ? null : [i * w / (v.length - 1), h - 1 - (hi > lo ? (x - lo) / (hi - lo) * (h - 2) : (h - 2) / 2)]).filter(Boolean);
  return `<svg class="sp" width="${w}" height="${h}"><polyline fill="none" stroke="currentColor" stroke-width="1.4" points="${pts.map(p => p.join(",")).join(" ")}"/></svg> `;
}
const f = (x, d) => x === null || x === undefined ? "–" : x.toLocaleString("ja-JP", {minimumFractionDigits: d, maximumFractionDigits: d});
function cell(k, r) {
  const v = r[k];
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button><a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (k === "加点") {
    if (!r.通過) return `<td class="s">–</td>`;
    const b = r.内訳, m = [];
    if (b.累進配当) m.push("累進+1"); if (b.組み合わせ) m.push(`${b.組み合わせ}+${b["BPS・DOE"]}`);
    return `<td><span class="pt">${v}</span> <small class="s">${m.join("・")}</small></td>`;
  }
  if (k === "連続増配") return `<td class="${v >= 5 ? "g" : ""}">${v === null || v === undefined ? "–" : v + "期"}</td>`;
  if (k === "配当10期") return `<td>${spark(v)}${r.配当倍 ? f(r.配当倍, 2) + "倍" : "–"}${r.減配 ? ` <small class="w">減配${r.減配}</small>` : ""}</td>`;
  if (k === "EPS倍") return `<td class="${v >= 2 ? "g" : "w"}">${v ? f(v, 2) + "倍" : "–"}</td>`;
  if (k === "BPS10期") return `<td>${spark(v)}${r.BPS倍 ? f(r.BPS倍, 2) + "倍" : "–"}${r.BPS毎期増 ? '<span class="mk">毎期</span>' : ""}</td>`;
  if (k === "DOE") return `<td>${f(v, 1)}${r.DOE記載 ? '<span class="mk">記載</span>' : ""}${r.累進配当 ? '<span class="mk">累進</span>' : ""}</td>`;
  if (k === "株価") return `<td>${f(v, 1)}</td>`;
  if (["配当利回り","PBR"].includes(k)) return `<td>${f(v, 2)}</td>`;
  if (["PER","ROE","ROA","自己資本比率"].includes(k)) return `<td>${f(v, 1)}</td>`;
  if (k === "時価総額") return `<td>${f(v, 0)}</td>`;
  if (k === "業種") return `<td style="text-align:left">${v || "–"}</td>`;
  if (k === "方針") return `<td>${v ? `<button class="more" data-c="${r.銘柄}">方針</button>` : "–"}</td>`;
  return `<td>${v ?? "–"}</td>`;
}
function draw() {
  const showFail = document.getElementById("showFail").checked;
  let rows = D.rows.filter(r => r.通過 || showFail);
  if (sortCol) {
    const key = SORTKEY[sortCol] || sortCol;
    rows.sort((a, b) => {
      if (a.通過 !== b.通過) return a.通過 ? -1 : 1;
      let x = a[key], y = b[key];
      if (x === null || x === undefined || typeof x === "string") return 1;
      if (y === null || y === undefined || typeof y === "string") return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
    });
  }
  document.getElementById("count").textContent = `両方を満たした ${D.count} 銘柄（第1段階を通ったのは ${D.stage1} 銘柄）`;
  const head = COLS.map(c => `<th data-c="${c}">${HEAD[c] || c}</th>`).join("");
  const body = rows.map(r => {
    let h = `<tr class="${r.通過 ? "" : "fail"}">` + COLS.map(c => cell(c, r)).join("") + "</tr>";
    if (!r.通過) h += `<tr class="detail"><td colspan="${COLS.length}">第2段階で落ちた理由：${r.理由}</td></tr>`;
    if (open.has(r.銘柄) && r.方針) h += `<tr class="detail"><td colspan="${COLS.length}">有価証券報告書（${r.期 ? r.期.split("〜")[1] + "期" : "最新"}）の配当方針：${r.方針}…</td></tr>`;
    return h;
  }).join("");
  document.getElementById("body").innerHTML = `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : ["PER","PBR"].includes(c);
    sortCol = c; draw();
  });
  document.querySelectorAll(".code").forEach(b => b.onclick = () => copyCode(b.dataset.code));
  document.querySelectorAll(".more").forEach(b => b.onclick = () => { open.has(b.dataset.c) ? open.delete(b.dataset.c) : open.add(b.dataset.c); draw(); });
}
document.getElementById("showFail").onchange = draw;
let toastTimer = null;
async function copyCode(code) {
  let ok = false;
  try { await navigator.clipboard.writeText(code); ok = true; } catch (e) {
    const t = document.createElement("textarea");
    t.value = code; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { ok = document.execCommand("copy"); } catch (e2) {}
    t.remove();
  }
  document.getElementById("toastMsg").textContent =
    ok ? `${code} をコピーしました。iSPEEDの検索に貼り付けてください` : `コピーできませんでした（コード ${code}）`;
  const el = document.getElementById("toast");
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 3500);
}
draw();
</script></body></html>
""".replace("__DATA__", data)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(out)
    print(f"作成: {out / 'renzoku.html'}  両方を満たした {p['count']}銘柄 / 第1段階 {p['stage1']}銘柄")
