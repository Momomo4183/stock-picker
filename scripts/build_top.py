# -*- coding: utf-8 -*-
"""トップページ（docs/index.html）と、共通する銘柄のページ（docs/common.html）を作る。

2026-10-18 ご本人の依頼:
  共通する銘柄は次の4つ（同日、グロース株×期待値投資の表から変更）
    ・4つのページすべてに載る銘柄（高配当株 15指標・グロース株・連続増配株・期待値投資）
    ・高配当株 × グロース株 × 連続増配株
    ・高配当株 × グロース株 × 期待値投資
    ・高配当株 × 連続増配株 × 期待値投資

「載っている」の扱い:
  高配当株 15指標チェック … ページに載っている銘柄（配当利回り3%以上・時価総額300億円以上）
  グロース株の候補       … ページに載っている銘柄
  連続増配株             … 第1段階と第2段階の両方を満たした銘柄
  期待値投資             … ページに載っている銘柄
4つのページを作ったあとに実行する（各ページの json を読む）。

使い方:
    python scripts/build_top.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAV = [("./", "トップ"), ("check15.html", "高配当株 15指標チェック"), ("growth.html", "グロース株の候補"),
       ("renzoku.html", "連続増配株"), ("kitaichi.html", "期待値投資"), ("common.html", "共通する銘柄")]
# PER検索（2026-10-18 ご本人の依頼でトップに検索欄を置いた）。銘柄ごとのPERは build_per_data.py が
# docs/per/コード.csv に、銘柄一覧は build_per_page.py が docs/per/index.json に作る
SEARCH_CSS = """form{display:flex;gap:8px;margin:4px 0 12px}
input{flex:1;min-width:0;font:inherit;font-size:16px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
button.go{font:inherit;font-weight:700;padding:9px 16px;border:0;border-radius:8px;background:var(--accent);color:#fff;cursor:pointer}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.name{font-size:17px;font-weight:700}.name a{color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:10px}
.k{font-size:11.5px;color:var(--sub)}.v{font-size:18px;font-weight:700}
.buy{color:var(--good)}.sell{color:var(--warn)}.s{color:var(--sub)}
.big{width:100%;height:auto}
.legend{font-size:11.5px;color:var(--sub);margin-bottom:4px}
.msg{color:var(--warn);font-size:13px;margin:6px 2px}
.recent{font-size:12.5px;color:var(--sub)}.recent button{font:inherit;font-size:12px;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0;cursor:pointer}
.search{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:14px}
.st{font-weight:700;font-size:15.5px;color:var(--accent)}.sd{font-size:12.5px;color:var(--sub);margin:2px 0 8px}
.search .card{background:var(--bg)}
.perdesc{font-size:12px;color:var(--sub);margin-top:6px}.perdesc summary{cursor:pointer;color:var(--ink)}
"""
SEARCH_HTML = """<div class="search"><div class="st">PER検索</div><div class="sd">銘柄コードか銘柄名を入れると、過去10年のPERの推移と幅、今のPERの位置（買い・売りの目安）を表示します。</div>
<form id="f"><input id="q" list="codes" placeholder="銘柄コード（例 7203）か銘柄名" autocomplete="off" inputmode="search"><button class="go">検索</button></form>
<datalist id="codes"></datalist>
<div class="recent" id="recent"></div>
<div class="msg" id="msg"></div>
<div id="out"></div>
<details class="perdesc"><summary>PERの見方</summary>PER＝月末の株価 ÷ その時点で発表済みの通期EPS（有価証券報告書、株式分割は調整済み。発表は期末の約3か月後として扱う）。
幅は過去10年の毎月のPERの<b>下から1割〜上から1割</b>、真ん中は<b>中央値</b>。今のPERが中央値以下なら<b class="buy">買い</b>、上なら<b class="sell">売り</b>の目安（期待値投資のページと同じ）。EPSが赤字の月は除いています。PERの幅は過去の話で、同じ幅に戻る保証はありません。</details>
<div class="sd" id="perCount"></div></div>
"""
SEARCH_JS = """let IDX = {stocks: {}};
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const f = (x, d) => x === null || x === undefined || isNaN(x) ? "–" : Number(x).toLocaleString("ja-JP", {minimumFractionDigits: d, maximumFractionDigits: d});
const q = (a, p) => { const s = a.slice().sort((x, y) => x - y), i = (s.length - 1) * p, lo = Math.floor(i); return s[lo] + (s[Math.ceil(i)] - s[lo]) * (i - lo); };
function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } }
function perChart(s, b, w, h) {
  const vals = s.map(x => x[1]).concat([b.now]).filter(x => x !== null);
  const top = Math.max(...vals, b.hi) * 1.05, bot = Math.max(0, Math.min(...vals, b.lo) * 0.9);
  const padL = 36, padB = 20, padT = 8, padR = 12;
  const X = i => padL + i * (w - padL - padR) / s.length, Y = v => padT + (top - v) / (top - bot) * (h - padT - padB);
  let g = `<svg viewBox="0 0 ${w} ${h}" class="big">`;
  g += `<rect x="${padL}" y="${Y(b.hi)}" width="${w - padL - padR}" height="${Y(b.lo) - Y(b.hi)}" fill="var(--band)"/>`;
  g += `<line x1="${padL}" x2="${w - padR}" y1="${Y(b.mid)}" y2="${Y(b.mid)}" stroke="var(--sub)" stroke-dasharray="3 3" stroke-width="1"/>`;
  let seg = [], path = "";
  s.forEach((x, i) => { if (x[1] === null) { if (seg.length) path += `<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${seg.join(" ")}"/>`; seg = []; } else seg.push(X(i) + "," + Y(x[1])); });
  if (seg.length) path += `<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${seg.join(" ")}"/>`;
  g += path;
  if (b.now !== null) {
    g += `<circle cx="${X(s.length)}" cy="${Y(b.now)}" r="4.5" fill="${b.now <= b.mid ? "var(--good)" : "var(--warn)"}"/>`;
    g += `<text x="${X(s.length) - 6}" y="${Y(b.now) - 8}" font-size="11" text-anchor="end" fill="var(--ink)">今 ${b.now.toFixed(1)}</text>`;
  }
  for (const v of [b.hi, b.mid, b.lo]) g += `<text x="${padL - 5}" y="${Y(v) + 4}" font-size="11" text-anchor="end" fill="var(--sub)">${v.toFixed(1)}</text>`;
  let last = "";
  s.forEach((x, i) => { const y = x[0].slice(0, 4); if (y !== last && x[0].endsWith("-01")) g += `<text x="${X(i)}" y="${h - 5}" font-size="11" text-anchor="middle" fill="var(--sub)">${y}</text>`; last = y; });
  return g + "</svg>";
}
function resolve(text) {
  text = text.trim().replace(/[０-９Ａ-Ｚａ-ｚ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0)).toUpperCase();
  const m = text.match(/^([0-9][0-9A-Z]{3})/);
  if (m && IDX.stocks[m[1]]) return m[1];
  const hit = Object.entries(IDX.stocks).filter(([c, v]) => v[0].includes(text.trim()));
  return hit.length === 1 ? hit[0][0] : (m ? m[1] : null);
}
async function show(code) {
  const msg = document.getElementById("msg"), out = document.getElementById("out");
  msg.textContent = ""; out.innerHTML = "";
  if (!code) { msg.textContent = "銘柄コード（4桁）か、銘柄名の一部を入れてください。"; return; }
  const info = IDX.stocks[code];
  if (!info) { msg.textContent = `${code} のデータはありません（決算書や有価証券報告書が取れない銘柄、上場して間もない銘柄など）。`; return; }
  let rows;
  try {
    const t = await (await fetch(`per/${code}.csv`, {cache: "no-cache"})).text();
    rows = t.trim().split("\\n").slice(1).map(l => { const [ym, p, e, per] = l.split(","); return [ym, +p, +e, per === "" ? null : +per]; });
  } catch (e) { msg.textContent = "データを読めませんでした。少し待ってからもう一度お試しください。"; return; }
  const pers = rows.map(r => r[3]).filter(x => x !== null);
  const eps = rows[rows.length - 1][2], price = info[1];
  const now = eps > 0 ? price / eps : null;
  const b = pers.length >= 12 ? {lo: q(pers, 0.1), mid: q(pers, 0.5), hi: q(pers, 0.9), now} : null;
  const pos = b && now !== null && b.hi > b.lo ? Math.round((now - b.lo) / (b.hi - b.lo) * 100) : null;
  const sig = b && now !== null ? (now <= b.mid ? "買い" : "売り") : null;
  let h = `<div class="card"><div class="name"><a href="${QUOTE(code)}" target="_blank" rel="noopener">${code} ${info[0]}</a></div>
  <div class="grid">
   <div><div class="k">目安</div><div class="v ${sig === "買い" ? "buy" : "sell"}">${sig || "–"} <small class="s">${pos === null ? "" : pos + "%"}</small></div></div>
   <div><div class="k">今のPER</div><div class="v">${now === null ? "赤字" : f(now, 1)}</div></div>
   <div><div class="k">PERの幅（下〜上）</div><div class="v">${b ? f(b.lo, 1) + "〜" + f(b.hi, 1) : "–"}</div></div>
   <div><div class="k">真ん中（中央値）</div><div class="v">${b ? f(b.mid, 1) : "–"}</div></div>
   <div><div class="k">株価（${IDX.asof}）</div><div class="v">${f(price, 1)}</div></div>
   <div><div class="k">直近の通期EPS</div><div class="v">${f(eps, 1)}</div></div>
  </div></div>`;
  if (b) h += `<div class="card"><div class="legend">PERの推移（月末、${rows[0][0]}〜${rows[rows.length - 1][0]}）。帯＝幅、点線＝中央値、点＝今。位置は 0%＝幅の下、100%＝上（0未満・100超は幅の外）</div>${perChart(rows.map(r => [r[0], r[3]]), b, 680, 230)}</div>`;
  else h += `<div class="card s">PERを出せる月が少ないため、幅は出していません（赤字の期が多い・データが短いなど）。</div>`;
  out.innerHTML = h;
  let rec = (store("per_recent") || []).filter(c => c !== code); rec.unshift(code); store("per_recent", rec.slice(0, 8)); drawRecent();
  history.replaceState(null, "", "#" + code);
}
function drawRecent() {
  const rec = (store("per_recent") || []).filter(c => IDX.stocks[c]);
  document.getElementById("recent").innerHTML = rec.length ? "最近：" + rec.map(c => `<button data-c="${c}">${c} ${IDX.stocks[c][0]}</button>`).join("") : "";
  document.querySelectorAll("#recent button").forEach(b => b.onclick = () => { document.getElementById("q").value = b.dataset.c; show(b.dataset.c); });
}
document.getElementById("f").onsubmit = e => { e.preventDefault(); show(resolve(document.getElementById("q").value)); };
(async () => {
  try { IDX = await (await fetch("per/index.json", {cache: "no-cache"})).json(); } catch (e) { document.getElementById("msg").textContent = "銘柄一覧を読めませんでした。"; return; }
  document.getElementById("perCount").textContent = `${Object.keys(IDX.stocks).length} 銘柄から検索できます（株価 ${IDX.asof} 時点）`;
  document.getElementById("codes").innerHTML = Object.entries(IDX.stocks).map(([c, v]) => `<option value="${c} ${v[0]}">`).join("");
  drawRecent();
  const h = location.hash.slice(1);
  if (h) { document.getElementById("q").value = h; show(resolve(h)); }
})();
"""
CSS = """:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00;--band:#0c6f7922}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050;--band:#4fb6bf2e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 6px}
h1{margin:0;font-size:19px}
h2{font-size:16px;margin:18px 2px 6px}
.meta{color:var(--sub);font-size:12px;margin-top:4px}
.nav{font-size:12.5px;margin-top:6px}.nav a{color:var(--accent);margin-right:14px}
section{padding:6px 14px 40px}
.desc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
.desc b{color:var(--ink)}"""


def code(s: str) -> str:
    return s.split(" ")[0]


def nav(self_: str) -> str:
    return '<div class="nav">' + "".join(f'<a href="{h}">{t}</a>' for h, t in NAV if h != self_) + "</div>"


def build(docs: Path) -> dict:
    load = lambda n: json.loads((docs / n).read_text(encoding="utf-8"))
    c15, gr, rz, kt = load("check15.json"), load("growth.json"), load("renzoku.json"), load("kitaichi.json")
    C = {code(r["銘柄"]): r for r in c15["rows"]}
    G = {code(r["銘柄"]): r for r in gr["rows"]}
    R = {code(r["銘柄"]): r for r in rz["rows"] if r["通過"]}
    K = {code(r["銘柄"]): r for r in kt["rows"]}

    def row(k):
        c, g, r, x = C.get(k), G.get(k), R.get(k), K.get(k)
        base = x or r or g or c
        return {"銘柄": base["銘柄"],
                "目安": x["目安"] if x else None, "PER帯": x["PER"] if x else None,
                "PEG": g["PEG"] if g else None,
                "15指標": c["合格"] if c else None,
                "加点": r["加点"] if r else None,
                "株価": base["株価"],
                "配当利回り": (x or r or c or {}).get("配当利回り"),
                "配当性向": (x or r or {}).get("配当性向"),
                "売上成長": g["売上成長"] if g else None, "営業利益成長": g["営業利益成長"] if g else None,
                "売上11期": x["売上"] if x else None, "営業利益10期": x["営業利益"] if x else None,
                "業種": base.get("業種")}

    order = lambda rows: sorted(rows, key=lambda z: (z["目安"] != "買い", z["PER帯"]["pos"] if z["PER帯"] and z["PER帯"]["pos"] is not None else 999,
                                                   -(z["加点"] or 0), -(z["15指標"][0] if z["15指標"] else 0)))
    sets = {"高配当株": set(C), "グロース株": set(G), "連続増配株": set(R), "期待値投資": set(K)}
    defs = [("4つのページすべてに載る銘柄", ["高配当株", "グロース株", "連続増配株", "期待値投資"]),
            ("高配当株 × グロース株 × 連続増配株", ["高配当株", "グロース株", "連続増配株"]),
            ("高配当株 × グロース株 × 期待値投資", ["高配当株", "グロース株", "期待値投資"]),
            ("高配当株 × 連続増配株 × 期待値投資", ["高配当株", "連続増配株", "期待値投資"])]
    sections = []
    for title, names in defs:
        hit = sorted(set.intersection(*(sets[x] for x in names)))
        sections.append({"title": title, "pages": names, "rows": order([row(k) for k in hit])})
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": rz["asof"],
               "counts": {k: len(v) for k, v in sets.items()}, "sections": sections}
    (docs / "common.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "common.html").write_text(render_common(payload), encoding="utf-8")
    (docs / "index.html").write_text(render_top(payload), encoding="utf-8")
    return payload


def render_top(p: dict) -> str:
    n = p["counts"]
    cards = [
        ("check15.html", "高配当株 15指標チェック", f"{n['高配当株']}銘柄",
         "配当利回り3%以上・時価総額300億円以上の銘柄を、note「高配当株の15指標」の考え方で採点。"),
        ("growth.html", "グロース株の候補", f"{n['グロース株']}銘柄",
         "売上・営業利益が年10%以上伸びている銘柄。PEG（PER÷利益の伸び）で割安さを見る。"),
        ("renzoku.html", "連続増配株", f"{n['連続増配株']}銘柄",
         "今の割安さ・収益性（第1段階）と、過去10期のEPS・BPS・配当（第2段階）を満たす銘柄。累進配当・DOE・BPSの伸びなどで加点。"),
        ("kitaichi.html", "期待値投資", f"{n['期待値投資']}銘柄",
         "配当利回り2.5%以上・配当性向50%以下で、売上が10期連続で増え、営業利益も伸びている銘柄。過去10年のPERの幅と、今のPERの位置（買い・売りの目安）。"),
        ("common.html", "共通する銘柄", "・".join(f"{len(x['rows'])}" for x in p["sections"]) + "銘柄",
         "上の4つのページすべてに載る銘柄と、高配当株を含む3つの組み合わせ（×グロース×連続増配、×グロース×期待値、×連続増配×期待値）に載る銘柄。"),
    ]
    items = "".join(f'<a class="card" href="{h}"><div class="t">{t}<span>{c}</span></div><div class="d">{d}</div></a>'
                    for h, t, c, d in cards)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>銘柄ピックアップ</title>
<style>{CSS}
.card{{display:block;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px;color:var(--ink);text-decoration:none}}
.card:hover{{border-color:var(--accent)}}
.t{{font-weight:700;font-size:15.5px;color:var(--accent)}}.t span{{float:right;color:var(--sub);font-weight:600;font-size:12.5px}}
.d{{font-size:12.5px;color:var(--sub);margin-top:3px}}
{SEARCH_CSS}</style></head><body>
<header><h1>銘柄ピックアップ</h1><div class="meta">株価 {p['asof']['株価']} 時点 ／ 作成 {p['generated']}</div></header>
<section>{SEARCH_HTML}{items}
<div class="desc">更新はPCの「更新」から手動で行います。どのページも候補を並べるだけで、売買の判断はご自身で行ってください。</div>
</section><script>{SEARCH_JS}</script></body></html>
"""


def render_common(p: dict) -> str:
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>共通する銘柄</title>
<style>__CSS__
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
summary{color:var(--ink);font-weight:600;cursor:pointer}
dl{margin:8px 0 2px}dt{color:var(--ink);font-weight:600;margin-top:6px}dd{margin:0}
.count{font-size:12px;color:var(--sub);margin:2px 2px 8px}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px;font-size:13px;color:var(--sub)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:10em;max-width:11.5em}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.buy{color:var(--good);font-weight:700}.sell{color:var(--warn);font-weight:700}.g{color:var(--good);font-weight:700}.w{color:var(--warn)}.s{color:var(--sub)}
.pt{font-weight:700;font-size:13.5px}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
svg{vertical-align:middle;display:inline-block}
.chartbtn{background:none;border:0;padding:0;cursor:pointer;color:var(--accent)}
tr.detail td{white-space:normal;text-align:left;background:var(--hi);position:static}
.big{width:100%;max-width:640px;height:auto}
.legend{font-size:11.5px;color:var(--sub)}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>共通する銘柄</h1><div class="meta" id="meta"></div>
__NAV__</header>
<section>
<div class="desc">ほかのページに重ねて載っている銘柄です。期待値投資を含む表は、PERの目安（過去10年の幅の真ん中より下なら<b class="buy">買い</b>、上なら<b class="sell">売り</b>）の順、含まない表は連続増配の加点・15指標の多い順に並べています。グラフを押すと大きく表示。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー。</div>
<details><summary>各列の見方</summary><dl>
<dt>目安・今のPER・PERの幅・グラフ</dt><dd>期待値投資のページと同じ（過去10年の毎月のPERの、下から1割〜上から1割の幅と中央値）。</dd>
<dt>PEG</dt><dd>グロース株の候補のページの PER÷利益の伸び。1倍以下が割安の目安。</dd>
<dt>15指標・加点</dt><dd>高配当株 15指標チェックの合格数、連続増配株のページの加点（最大8点）。</dd>
<dt>売上・営業利益の伸び</dt><dd>グロース株の候補のページの年平均の伸び（4〜5期）。</dd>
</dl></details>
<div id="sections"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const n = D.counts;
document.getElementById("meta").textContent = `株価 ${D.asof.株価} 時点 ／ 作成 ${D.generated}`;
const PAGE_COLS = {"期待値投資": ["目安","PER今","PER幅","グラフ"], "グロース株": ["PEG"], "高配当株": ["15指標"], "連続増配株": ["加点"]};
const TABLES = {};
document.getElementById("sections").innerHTML = D.sections.map((sec, i) => {
  const id = "t" + i;
  let cols = ["銘柄"];
  for (const pg of ["期待値投資","グロース株","高配当株","連続増配株"]) if (sec.pages.includes(pg)) cols = cols.concat(PAGE_COLS[pg]);
  cols = cols.concat(["株価","配当利回り","配当性向"]);
  if (sec.pages.includes("グロース株")) cols = cols.concat(["売上成長","営業利益成長"]);
  cols.push("業種");
  TABLES[id] = {rows: sec.rows, cols};
  const each = sec.pages.map(pg => `${pg} ${n[pg]}`).join("・");
  return `<h2>${sec.title}</h2><div class="count">${sec.rows.length} 銘柄（${each} の${sec.pages.length === 4 ? "すべて" : "3つ"}に載る）</div><div id="${id}"></div>`;
}).join("");
const HEAD = {"PER今":"今のPER","PER幅":"PERの幅（中央）","グラフ":"PERの推移（10年）","配当利回り":"利回り%","配当性向":"配当性向%","売上成長":"売上の伸び%","営業利益成長":"営業利益の伸び%","売上11期":"売上（11期）","営業利益10期":"営業利益（10期）"};
const val = v => Array.isArray(v) ? v[0] : v;
const KEY = {"目安": r => r.PER帯 ? r.PER帯.pos : null, "PER今": r => r.PER帯 ? r.PER帯.now : null, "PER幅": r => r.PER帯 ? r.PER帯.mid : null,
             "PEG": r => val(r.PEG), "15指標": r => r["15指標"] ? r["15指標"][0] : null};
const f = (x, d) => x === null || x === undefined ? "–" : Number(x).toLocaleString("ja-JP", {minimumFractionDigits: d, maximumFractionDigits: d});
function spark(v) {
  if (!v || v.length < 2) return "–";
  const lo = Math.min(...v), hi = Math.max(...v), w = 54, h = 16;
  const pts = v.map((x, i) => [i * w / (v.length - 1), h - 1 - (hi > lo ? (x - lo) / (hi - lo) * (h - 2) : (h - 2) / 2)]);
  return `<svg width="${w}" height="${h}"><polyline fill="none" stroke="currentColor" stroke-width="1.4" points="${pts.map(p => p.join(",")).join(" ")}"/></svg>`;
}
function perChart(b, w, h, big) {
  const s = b.series, vals = s.map(x => x[1]).concat([b.now]);
  const top = Math.max(...vals, b.hi) * 1.05, bot = Math.max(0, Math.min(...vals, b.lo) * 0.9);
  const padL = big ? 34 : 2, padB = big ? 18 : 2, padT = big ? 6 : 2, padR = big ? 10 : 6;
  const X = i => padL + i * (w - padL - padR) / s.length, Y = v => padT + (top - v) / (top - bot) * (h - padT - padB);
  let g = `<svg viewBox="0 0 ${w} ${h}" width="${big ? "100%" : w}" ${big ? 'class="big"' : `height="${h}"`}>`;
  g += `<rect x="${padL}" y="${Y(b.hi)}" width="${w - padL - padR}" height="${Y(b.lo) - Y(b.hi)}" fill="var(--band)"/>`;
  g += `<line x1="${padL}" x2="${w - padR}" y1="${Y(b.mid)}" y2="${Y(b.mid)}" stroke="var(--sub)" stroke-dasharray="3 3" stroke-width="1"/>`;
  g += `<polyline fill="none" stroke="var(--accent)" stroke-width="${big ? 1.8 : 1.3}" points="${s.map((x, i) => X(i) + "," + Y(x[1])).join(" ")}"/>`;
  g += `<circle cx="${X(s.length)}" cy="${Y(b.now)}" r="${big ? 4 : 2.6}" fill="${b.now <= b.mid ? "var(--good)" : "var(--warn)"}"/>`;
  if (big) {
    for (const v of [b.hi, b.mid, b.lo]) g += `<text x="${padL - 4}" y="${Y(v) + 4}" font-size="10" text-anchor="end" fill="var(--sub)">${v}</text>`;
    let last = "";
    s.forEach((x, i) => { const y = x[0].slice(0, 4); if (y !== last && x[0].endsWith("-01")) g += `<text x="${X(i)}" y="${h - 4}" font-size="10" text-anchor="middle" fill="var(--sub)">${y}</text>`; last = y; });
    g += `<text x="${X(s.length)}" y="${Y(b.now) - 7}" font-size="10" text-anchor="end" fill="var(--ink)">今 ${b.now}</text>`;
  }
  return g + "</svg>";
}
function cell(k, r) {
  const b = r.PER帯, v = r[k];
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button><a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (["目安","PER今","PER幅","グラフ"].includes(k) && !b) return `<td class="s">–</td>`;
  if (k === "目安") return `<td><span class="${r.目安 === "買い" ? "buy" : "sell"}">${r.目安}</span> <small class="s">${b.pos}%</small></td>`;
  if (k === "PER今") return `<td>${f(b.now, 1)}</td>`;
  if (k === "PER幅") return `<td>${f(b.lo, 1)}〜${f(b.hi, 1)} <small class="s">（${f(b.mid, 1)}）</small></td>`;
  if (k === "グラフ") return `<td><button class="chartbtn" data-c="${r.銘柄}" aria-label="グラフを大きく">${perChart(b, 120, 34, false)}</button></td>`;
  if (k === "PEG") return v === null || v === undefined ? "<td>–</td>" : Array.isArray(v) ? `<td class="w">${f(v[0], 2)} <small>${v[1]}</small></td>` : `<td class="${v <= 1 ? "g" : ""}">${f(v, 2)}</td>`;
  if (k === "15指標") return `<td class="pt">${v ? v[0] + "/" + v[1] : "–"}</td>`;
  if (k === "加点") return `<td class="pt">${v ?? "–"}</td>`;
  if (k === "株価") return `<td>${f(v, 1)}</td>`;
  if (k === "配当利回り") return `<td>${f(v, 2)}</td>`;
  if (k === "配当性向") return `<td>${f(v, 0)}</td>`;
  if (k === "売上成長" || k === "営業利益成長") return `<td>${f(val(v), 1)}</td>`;
  if (k === "売上11期" || k === "営業利益10期") return `<td>${spark(v)}</td>`;
  if (k === "業種") return `<td style="text-align:left">${v || "–"}</td>`;
  return `<td>${v ?? "–"}</td>`;
}
const state = {};
Object.keys(TABLES).forEach(id => state[id] = {col: null, asc: true});
const open = new Set();
function draw(id) {
  const T = TABLES[id], st = state[id];
  if (!T.rows.length) { document.getElementById(id).innerHTML = `<div class="empty">今は該当する銘柄がありません。更新のたびに作り直すので、次の更新で出てくることがあります。</div>`; return; }
  let rows = T.rows.slice();
  if (st.col) {
    const get = KEY[st.col] || (r => val(r[st.col]));
    rows.sort((a, b) => {
      const x = get(a), y = get(b);
      if (x === null || x === undefined || typeof x === "string") return 1;
      if (y === null || y === undefined || typeof y === "string") return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (st.asc ? 1 : -1);
    });
  }
  const head = T.cols.map(c => `<th data-c="${c}">${HEAD[c] || c}</th>`).join("");
  const body = rows.map(r => {
    let h = "<tr>" + T.cols.map(c => cell(c, r)).join("") + "</tr>";
    const key = id + r.銘柄;
    if (open.has(key) && r.PER帯) h += `<tr class="detail"><td colspan="${T.cols.length}"><div class="legend">${r.銘柄}　PER の推移（月末）。帯＝過去10年の幅 ${r.PER帯.lo}〜${r.PER帯.hi}、点線＝中央値 ${r.PER帯.mid}、点＝今 ${r.PER帯.now}</div>${perChart(r.PER帯, 640, 170, true)}</td></tr>`;
    return h;
  }).join("");
  const el = document.getElementById(id);
  el.innerHTML = `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  el.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    st.asc = st.col === c ? !st.asc : ["目安","PER今","PER幅","PEG"].includes(c);
    st.col = c; draw(id);
  });
  el.querySelectorAll(".code").forEach(b => b.onclick = () => copyCode(b.dataset.code));
  el.querySelectorAll(".chartbtn").forEach(b => b.onclick = () => { const k = id + b.dataset.c; open.has(k) ? open.delete(k) : open.add(k); draw(id); });
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
Object.keys(TABLES).forEach(draw);
</script></body></html>
""".replace("__CSS__", CSS).replace("__NAV__", nav("common.html")).replace("__DATA__", json.dumps(p, ensure_ascii=False))


if __name__ == "__main__":
    docs = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(docs)
    print(f"作成: {docs / 'index.html'}・{docs / 'common.html'}  " + " / ".join(f"{x['title']} {len(x['rows'])}" for x in p["sections"]))
