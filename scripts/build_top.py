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
</style></head><body>
<header><h1>銘柄ピックアップ</h1><div class="meta">株価 {p['asof']['株価']} 時点 ／ 作成 {p['generated']}</div></header>
<section>{items}
<div class="desc">更新はPCの「更新」から手動で行います。どのページも候補を並べるだけで、売買の判断はご自身で行ってください。</div>
</section></body></html>
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
