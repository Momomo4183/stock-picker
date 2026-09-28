# -*- coding: utf-8 -*-
"""グロース株の候補を並べ、その中から割安なものを探すページ（docs/growth.html）を作る。

2026-09-28 本人の依頼。「グロース株をピックアップし、さらにその中から割安なものを探したい」。

対象       時価総額100億円以上・売買代金（20日平均）5,000万円以上
           グロース株は小さめの会社が多いので配当のページより下限を下げ、代わりに
           売買のしやすさで絞る
グロース株  次をすべて満たす（年次決算4〜5期の年平均で見る）
           ・売上の成長率 年10%以上
           ・営業利益の成長率 年10%以上（最も古い期も直近も営業黒字）
           ・直近期も増収
割安さ     PEG（PER ÷ 純利益の年平均成長率%）を主に見る。1倍以下を割安とする
           （ピーター・リンチの考え方）。利益がまだ小さい会社向けにPSRも並べる

成長率は、最も古い期から直近の期までの年平均（4〜5期なので3〜4年分）。
株式分割で1株あたりの値が飛ぶのを避けるため、EPSではなく純利益で測る。

**このページの条件で将来の値上がりが確かめられたわけではない**。年次決算が4〜5期しか
取れないため、過去に遡った検証がほとんどできない（15指標の検証と同じ壁）。

使い方:
    python scripts/build_growth.py
"""
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import load  # noqa: E402
import fetch_statements  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MIN_CAP, MIN_DAI = 100, 50_000_000
MIN_GROWTH = 0.10
# PEGに使う成長率の上限。最も古い期（2021〜22年度）はコロナで利益が落ち込んだ会社が多く、
# そこから測ると年+100〜400%になってPEGが0近くに潰れる（2026-09-28 に発覚）。
# 純利益と営業利益の伸びの低いほうを使い、30%で頭打ちにする
PEG_GROWTH_CAP = 0.30
MIN_PER_FOR_PEG = 5          # PERがこれ未満は一時的な利益の疑い（割安の数に入れない）
COLUMNS = ["銘柄", "PEG", "株価", "売上成長", "増収", "直近売上", "営業利益成長", "利益成長",
           "営業利益率", "利益率の改善", "ROE", "営業CF", "PER", "PSR", "PBR",
           "6か月騰落", "荒さ", "時価総額億", "業種"]


def cagr(s: pd.Series):
    s = s.dropna()
    if len(s) < 3 or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return None
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / (len(s) - 1)) - 1)


def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def market_extras() -> pd.DataFrame:
    """売買代金（20日平均）と6か月騰落を株価データから出す。"""
    px = pd.read_pickle(sorted(glob.glob(str(DATA / "prices_*.pkl")))[-1])
    rows = []
    for c, d in px.items():
        d = d.dropna(subset=["Close"])
        if len(d) < 21:
            continue
        rows.append({"code": c,
                     "売買代金": float((d["Close"] * d["Volume"]).tail(20).mean()),
                     "6か月騰落": float(d["Close"].iloc[-1] / d["Close"].iloc[0] - 1)})
    return pd.DataFrame(rows)


def build(out_dir: Path) -> dict:
    df, asof = load()
    df = df.merge(market_extras(), on="code", how="left")
    base = df[(df["時価総額億"] >= MIN_CAP) & (df["売買代金"] >= MIN_DAI)].copy()
    print(f"対象 {len(base)}銘柄（時価総額{MIN_CAP}億円以上・売買代金{MIN_DAI / 1e4:,.0f}万円以上）",
          flush=True)
    stm = fetch_statements.update(base["code"].tolist())
    stm = stm[stm["error"].fillna("") == ""]
    by_code = {c: g.sort_values("決算期") for c, g in stm.groupby("code")}

    rows, judged = [], 0
    for _, r in base.iterrows():
        g = by_code.get(r["code"])
        if g is None:
            continue
        rev, op, ni = g["売上"].dropna(), g["営業利益"].dropna(), g["純利益"].dropna()
        if len(rev) < 3:
            continue
        judged += 1
        g_rev, g_op, g_ni = cagr(rev), cagr(op), cagr(ni)
        last_rev = float(rev.iloc[-1] / rev.iloc[-2] - 1) if rev.iloc[-2] > 0 else None
        # グロース株の条件
        if not (g_rev is not None and g_rev >= MIN_GROWTH and g_op is not None
                and g_op >= MIN_GROWTH and last_rev is not None and last_rev > 0):
            continue
        per = num(r["PER"])
        g_peg = min(g_ni, g_op, PEG_GROWTH_CAP) if g_ni and g_ni > 0 else None
        peg = per / (g_peg * 100) if per and g_peg else None
        ups = int((rev.diff().dropna() > 0).sum())
        margin_now = op.iloc[-1] / rev.iloc[-1] if rev.iloc[-1] else None
        margin_old = op.iloc[0] / rev.iloc[0] if rev.iloc[0] else None
        eq, net = num(g["純資産"].dropna().iloc[-1]) if g["純資産"].notna().any() else None, \
            num(ni.iloc[-1]) if len(ni) else None
        cf = g["営業CF"].dropna()
        cap = r["時価総額億"] * 1e8
        rec = {
            "銘柄": f"{r['code']} {r['name']}",
            "PEG": ([round(peg, 2), "要確認"] if peg is not None and per < MIN_PER_FOR_PEG
                    else round(peg, 2) if peg is not None else None),
            "株価": round(float(r["株価"]), 1),
            "売上成長": round(g_rev * 100, 1),
            "増収": f"{ups}/{len(rev) - 1}",
            "直近売上": round(last_rev * 100, 1),
            "営業利益成長": round(g_op * 100, 1),
            "利益成長": round(g_ni * 100, 1) if g_ni is not None else None,
            "営業利益率": round(margin_now * 100, 1) if margin_now is not None else None,
            "利益率の改善": (round((margin_now - margin_old) * 100, 1)
                        if margin_now is not None and margin_old is not None else None),
            "ROE": round(net / eq * 100, 1) if net is not None and eq and eq > 0 else None,
            "営業CF": (None if len(cf) < 2 else
                       "全期プラス" if (cf > 0).all() else f"マイナス{int((cf <= 0).sum())}期"),
            "PER": round(per, 1) if per else None,
            "PSR": round(cap / rev.iloc[-1], 2) if rev.iloc[-1] > 0 else None,
            "PBR": round(float(r["PBR"]), 2) if num(r["PBR"]) else None,
            "6か月騰落": round(float(r["6か月騰落"]) * 100, 1) if num(r["6か月騰落"]) is not None else None,
            "荒さ": round(float(r["荒さ"])) if num(r["荒さ"]) is not None else None,
            "時価総額億": round(float(r["時価総額億"])),
            "業種": r.get("sector") if isinstance(r.get("sector"), str) else None,
        }
        rows.append({k: rec.get(k) for k in COLUMNS})
    def peg_key(x):
        v = x["PEG"]
        if v is None:
            return (2, 0)
        if isinstance(v, list):          # 要確認は後ろへ
            return (1, v[0])
        return (0, v)
    rows.sort(key=peg_key)
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": asof,
               "universe": len(base), "judged": judged, "count": len(rows),
               "cheap": sum(1 for x in rows if isinstance(x["PEG"], float) and x["PEG"] <= 1),
               "condition": (f"時価総額{MIN_CAP}億円以上・売買代金{MIN_DAI / 1e4:,.0f}万円以上"
                             f"のうち、売上・営業利益とも年{MIN_GROWTH:.0%}以上の成長で直近期も増収"),
               "rows": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "growth.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    (out_dir / "growth.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    data = json.dumps(p, ensure_ascii=False)
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>グロース株の候補</title>
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
.bar{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 2px;font-size:12px;color:var(--sub)}
.bar label{display:flex;align-items:center;gap:6px;color:var(--ink);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:10em;max-width:11.5em}
td:last-child{text-align:left}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.g{color:var(--good);font-weight:700}.p{color:var(--good)}.w{color:var(--warn);font-weight:600}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>グロース株の候補</h1><div class="meta" id="meta"></div>
<div class="nav"><a href="./">配当株の買い場</a><a href="check15.html">高配当株 15指標チェック</a></div></header>
<section>
<div class="desc"><b>条件</b>　<span id="cond"></span><br>
並び順は<b>PEG</b>（PER÷利益の成長率）の低い順＝成長の速さに対して株価が安い順です。PEG 1倍以下が割安の目安。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー。<br>
※この条件で将来の値上がりが確かめられたわけではありません（決算が4〜5期しか遡れず、過去の検証ができないため）。</div>
<details><summary>各列の見方</summary><dl>
<dt>PEG</dt><dd>PER ÷ 利益の成長率（%）。1倍以下は割安（緑）、2倍超は割高（橙）の目安。成長が速い会社はPERが高くても割安になりうる、という考え方。成長率は純利益と営業利益の伸びの<b>低いほう</b>を使い、<b>年30%で頭打ち</b>にしています（4〜5期前はコロナで利益が落ち込んでいた会社が多く、そこから測ると伸びが極端に大きく出るため）。PERが5倍未満は一時的な利益の疑いがあるので「要確認」とし、割安の数に入れていません。</dd>
<dt>増収</dt><dd>何期のうち何期で売上が前期より増えたか。全期で増収なら緑。コロナからの回復なのか、安定した成長なのかを見分ける手がかり。</dd>
<dt>売上成長・営業利益成長・利益成長</dt><dd>最も古い期から直近の期までの年平均（4〜5期＝3〜4年分）。利益はEPSの代わりに純利益（株式分割で1株あたりの値が飛ぶのを避けるため）。20%以上は緑の太字。</dd>
<dt>直近売上</dt><dd>直近の期の売上の前期比。成長が続いているか。年平均より低いと橙（成長が鈍っている）。</dd>
<dt>営業利益率・利益率の改善</dt><dd>直近の営業利益率と、最も古い期からの変化（ポイント）。伸びるほど儲かる体質になっているか。</dd>
<dt>ROE</dt><dd>純利益 ÷ 純資産。15%以上は緑。</dd>
<dt>営業CF</dt><dd>取得できた全期でプラスか。利益が現金として入ってきているか。</dd>
<dt>PSR</dt><dd>時価総額 ÷ 売上。利益がまだ小さい会社の割安さを見る物差し。</dd>
<dt>6か月騰落</dt><dd>直近6か月の株価の変化。グロース投資では、強い（上がっている）株を選ぶ考え方もある。</dd>
<dt>荒さ</dt><dd>値動きの大きさ（全銘柄の中での位置）。グロース株は荒くなりやすい。</dd>
</dl></details>
<div class="bar"><span id="count"></span><label><input type="checkbox" id="cheapOnly">割安（PEG 1倍以下）だけ表示</label></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const GROW = new Set(["売上成長","営業利益成長","利益成長"]);
let sortCol = null, sortAsc = true;
document.getElementById("meta").textContent =
  `株価 ${D.asof.株価} 時点 ／ 対象 ${D.universe.toLocaleString()}銘柄 ／ 作成 ${D.generated}`;
document.getElementById("cond").textContent = D.condition;
const cheapBox = document.getElementById("cheapOnly");
cheapBox.onchange = draw;
function pct(x, plus) { return (plus && x > 0 ? "+" : "") + x + "%"; }
function cell(k, v, r) {
  if (v === null || v === undefined) return "<td>–</td>";
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button>` +
           `<a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (k === "PEG") {
    if (Array.isArray(v)) return `<td title="PERが5倍未満。一時的な利益で安く見えている可能性">${v[0].toFixed(2)} <small>要確認</small></td>`;
    return `<td class="${v <= 1 ? "g" : v > 2 ? "w" : ""}">${v.toFixed(2)}</td>`;
  }
  if (k === "増収") { const [a, b] = v.split("/").map(Number); return `<td class="${a === b ? "p" : ""}">${a}/${b}期</td>`; }
  if (k === "株価") return `<td>${v.toLocaleString("ja-JP",{maximumFractionDigits:1})}</td>`;
  if (GROW.has(k)) return `<td class="${v >= 20 ? "g" : "p"}">${pct(v, true)}</td>`;
  if (k === "直近売上") return `<td class="${v < r["売上成長"] ? "w" : "p"}">${pct(v, true)}</td>`;
  if (k === "利益率の改善") return `<td class="${v > 0 ? "p" : "w"}">${(v > 0 ? "+" : "") + v}pt</td>`;
  if (k === "営業利益率") return `<td>${v}%</td>`;
  if (k === "ROE") return `<td class="${v >= 15 ? "p" : ""}">${v}%</td>`;
  if (k === "営業CF") return `<td class="${v === "全期プラス" ? "p" : "w"}">${v}</td>`;
  if (k === "6か月騰落") return `<td>${pct(v, true)}</td>`;
  if (k === "荒さ") {
    const t = v < 33 ? ["穏やか","p"] : v < 67 ? ["普通",""] : ["荒い","w"];
    return `<td class="${t[1]}">${t[0]}</td>`;
  }
  if (k === "時価総額億") return `<td>${v.toLocaleString("ja-JP")}</td>`;
  if (k === "業種") return `<td>${v}</td>`;
  return `<td>${v}</td>`;
}
function draw() {
  let rows = D.rows.filter(r => !cheapBox.checked || (typeof r.PEG === "number" && r.PEG <= 1));
  if (sortCol) rows.sort((a, b) => {
    let x = a[sortCol], y = b[sortCol];
    if (Array.isArray(x)) x = x[0]; if (Array.isArray(y)) y = y[0];
    if (sortCol === "増収") { x = x ? Number(x.split("/")[0]) : null; y = y ? Number(y.split("/")[0]) : null; }
    if (x === null || x === undefined || typeof x === "string") return 1;
    if (y === null || y === undefined || typeof y === "string") return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
  });
  document.getElementById("count").textContent =
    `${rows.length} 銘柄（グロース株 ${D.count}、うち割安 ${D.cheap}）`;
  const cols = Object.keys(D.rows[0] || {});
  const head = cols.map(c => `<th data-c="${c}">${c.replace("億","")}</th>`).join("");
  const body = rows.map(r => "<tr>" + cols.map(c => cell(c, r[c], r)).join("") + "</tr>").join("");
  document.getElementById("body").innerHTML =
    `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : ["PEG","PER","PSR","PBR","荒さ"].includes(c);
    sortCol = c; draw();
  });
  document.querySelectorAll(".code").forEach(b => b.onclick = () => copyCode(b.dataset.code));
}
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
    print(f"作成: {out / 'growth.html'}  グロース株 {p['count']}銘柄（決算で判定できた {p['judged']}銘柄中）"
          f"・うち PEG 1倍以下 {p['cheap']}銘柄")
