# -*- coding: utf-8 -*-
"""トップページ（docs/index.html）と、3つのページに共通する銘柄のページ（docs/common.html）を作る。

2026-10-18 ご本人の依頼:
  「配当株の買い場」を削除し、高配当株（15指標チェック）・グロース株・連続増配株の
  3つすべてに上がっている銘柄のページを作る。0件なら 高配当株 × 連続増配株 にする。

「上がっている」の扱い:
  高配当株 15指標チェック … ページに載っている銘柄（配当利回り3%以上・時価総額300億円以上）
  グロース株の候補       … ページに載っている銘柄（売上・営業利益が年10%以上の成長など）
  連続増配株             … 第1段階と第2段階の両方を満たした銘柄
3つのページを作ったあとに実行する（各ページの json を読む）。

使い方:
    python scripts/build_top.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAV = [("./", "トップ"), ("check15.html", "高配当株 15指標チェック"), ("growth.html", "グロース株の候補"),
       ("renzoku.html", "連続増配株"), ("kitaichi.html", "期待値投資"), ("common.html", "3つに共通する銘柄")]
CSS = """:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 6px}
h1{margin:0;font-size:19px}
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
    c15, gr, rz = load("check15.json"), load("growth.json"), load("renzoku.json")
    C = {code(r["銘柄"]): r for r in c15["rows"]}
    G = {code(r["銘柄"]): r for r in gr["rows"]}
    R = {code(r["銘柄"]): r for r in rz["rows"] if r["通過"]}
    both = set(C) & set(R)
    three = both & set(G)
    mode = "3つ" if three else "高配当株 × 連続増配株"
    pick = three or both
    rows = []
    for k in pick:
        c, r, g = C[k], R[k], G.get(k, {})
        rows.append({"銘柄": r["銘柄"], "連続増配の加点": r["加点"], "加点の内訳": r["内訳"],
                     "15指標の合格": c["合格"], "PEG": g.get("PEG"),
                     "株価": r["株価"], "配当利回り": r["配当利回り"], "連続増配": r["連続増配"],
                     "配当10期": r["配当10期"], "配当倍": r["配当倍"], "減配": r["減配"],
                     "EPS倍": r["EPS倍"], "BPS倍": r["BPS倍"], "BPS毎期増": r["BPS毎期増"],
                     "売上成長": g.get("売上成長"), "営業利益成長": g.get("営業利益成長"),
                     "PER": r["PER"], "PBR": r["PBR"], "ROE": r["ROE"], "DOE": r["DOE"],
                     "業種": r["業種"]})
    rows.sort(key=lambda x: (-x["連続増配の加点"], -x["15指標の合格"][0], x["PEG"][0] if isinstance(x["PEG"], list) else (x["PEG"] or 9)))
    kt = docs / "kitaichi.json"
    n_kt = json.loads(kt.read_text(encoding="utf-8"))["count"] if kt.exists() else None
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": rz["asof"], "mode": mode,
               "count": len(rows), "counts": {"高配当株": len(C), "グロース株": len(G), "連続増配株": len(R),
                                              "3つ": len(three), "高配当株 × 連続増配株": len(both),
                                              "期待値投資": n_kt},
               "rows": rows}
    (docs / "common.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "common.html").write_text(render_common(payload), encoding="utf-8")
    (docs / "index.html").write_text(render_top(payload, c15, gr, rz), encoding="utf-8")
    return payload


def render_top(p: dict, c15: dict, gr: dict, rz: dict) -> str:
    n = p["counts"]
    cards = [
        ("check15.html", "高配当株 15指標チェック", f"{n['高配当株']}銘柄",
         "配当利回り3%以上・時価総額300億円以上の銘柄を、note「高配当株の15指標」の考え方で採点。"),
        ("growth.html", "グロース株の候補", f"{n['グロース株']}銘柄",
         "売上・営業利益が年10%以上伸びている銘柄。PEG（PER÷利益の伸び）で割安さを見る。"),
        ("renzoku.html", "連続増配株", f"{n['連続増配株']}銘柄",
         "今の割安さ・収益性（第1段階）と、過去10期のEPS・BPS・配当（第2段階）を満たす銘柄。累進配当・DOE・BPSの伸びで加点。"),
        ("kitaichi.html", "期待値投資", f"{n['期待値投資']}銘柄" if n.get("期待値投資") is not None else "",
         "配当利回り2.5%以上・配当性向50%以下で、売上が10期連続で増え、営業利益も伸びている銘柄。過去10年のPERの幅と、今のPERの位置（買い・売りの目安）を表示。"),
        ("common.html", "3つに共通する銘柄" if p["mode"] == "3つ" else "高配当株 × 連続増配株", f"{p['count']}銘柄",
         "上の3つのページすべてに載っている銘柄。" if p["mode"] == "3つ"
         else "3つすべてに載る銘柄が無いため、高配当株と連続増配株の両方に載る銘柄。"),
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
    data = json.dumps(p, ensure_ascii=False)
    title = "3つに共通する銘柄" if p["mode"] == "3つ" else "高配当株 × 連続増配株"
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
summary{color:var(--ink);font-weight:600;cursor:pointer}
dl{margin:8px 0 2px}dt{color:var(--ink);font-weight:600;margin-top:6px}dd{margin:0}
.count{font-size:12px;color:var(--sub);margin:8px 2px}
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
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
svg.sp{vertical-align:middle}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>__TITLE__</h1><div class="meta" id="meta"></div>
__NAV__</header>
<section>
<div class="desc" id="desc"></div>
<details><summary>各列の見方</summary><dl>
<dt>連続増配の加点</dt><dd>連続増配株のページの加点（累進配当+1、BPSとDOEの組み合わせで最大+4、連続増配5期以上・配当性向50%以下・営業CFで配当をまかなえている で各+1、最大8点）。</dd>
<dt>15指標</dt><dd>高配当株 15指標チェックで、基準を満たした数／判定できた数。</dd>
<dt>PEG</dt><dd>グロース株の候補のページの PER÷利益の伸び。1倍以下が割安の目安。</dd>
<dt>連続増配・配当（10期）・EPS・BPS</dt><dd>連続増配株のページと同じ（有価証券報告書の10期分）。</dd>
<dt>売上・営業利益の伸び</dt><dd>グロース株の候補のページの年平均の伸び（4〜5期）。</dd>
</dl></details>
<div class="count" id="count"></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const COLS = ["銘柄","連続増配の加点","15指標の合格","PEG","株価","配当利回り","連続増配","配当10期","EPS倍","BPS倍","売上成長","営業利益成長","PER","PBR","ROE","DOE","業種"];
const HEAD = {"連続増配の加点":"加点","15指標の合格":"15指標","配当利回り":"利回り%","配当10期":"配当（10期）","EPS倍":"EPS（10期）","BPS倍":"BPS（10期）","売上成長":"売上の伸び%","営業利益成長":"営業利益の伸び%","ROE":"ROE%","DOE":"DOE%"};
let sortCol = null, sortAsc = false;
document.getElementById("meta").textContent = `株価 ${D.asof.株価} 時点 ／ 作成 ${D.generated}`;
const n = D.counts;
document.getElementById("desc").innerHTML = (D.mode === "3つ"
  ? `<b>高配当株 15指標チェック</b>（${n.高配当株}）・<b>グロース株の候補</b>（${n.グロース株}）・<b>連続増配株</b>（${n.連続増配株}）の<b>3つすべて</b>に載っている銘柄です。`
  : `3つすべてに載る銘柄が無かったので、<b>高配当株 15指標チェック</b>（${n.高配当株}）と<b>連続増配株</b>（${n.連続増配株}）の両方に載っている銘柄です。`)
  + `<br>連続増配の加点が多い順。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー。`;
document.getElementById("count").textContent = `${D.count} 銘柄（参考：高配当株 × 連続増配株は ${n["高配当株 × 連続増配株"]} 銘柄）`;
const val = v => Array.isArray(v) ? v[0] : v;
const f = (x, d) => x === null || x === undefined ? "–" : Number(x).toLocaleString("ja-JP", {minimumFractionDigits: d, maximumFractionDigits: d});
function spark(v) {
  const xs = (v || []).filter(x => x !== null);
  if (xs.length < 2) return "";
  const lo = Math.min(...xs), hi = Math.max(...xs), w = 54, h = 16;
  const pts = v.map((x, i) => x === null ? null : [i * w / (v.length - 1), h - 1 - (hi > lo ? (x - lo) / (hi - lo) * (h - 2) : (h - 2) / 2)]).filter(Boolean);
  return `<svg class="sp" width="${w}" height="${h}"><polyline fill="none" stroke="currentColor" stroke-width="1.4" points="${pts.map(p => p.join(",")).join(" ")}"/></svg> `;
}
function cell(k, r) {
  const v = r[k];
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button><a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (k === "連続増配の加点") {
    const b = r.加点の内訳, m = [];
    if (b.累進配当) m.push("累進+1"); if (b.組み合わせ) m.push(`${b.組み合わせ}+${b["BPS・DOE"]}`);
    if (b.連続増配5期) m.push("増配5期+1"); if (b.性向50以下) m.push("性向+1"); if (b.CFで配当) m.push("CF+1");
    return `<td><span class="pt">${v}</span> <small class="s">${m.join("・")}</small></td>`;
  }
  if (k === "15指標の合格") return `<td class="pt">${v[0]}/${v[1]}</td>`;
  if (k === "PEG") return v === null || v === undefined ? "<td>–</td>" : Array.isArray(v) ? `<td class="w">${f(v[0], 2)} <small>${v[1]}</small></td>` : `<td class="${v <= 1 ? "g" : ""}">${f(v, 2)}</td>`;
  if (k === "連続増配") return `<td class="${v >= 5 ? "g" : ""}">${v === null || v === undefined ? "–" : v + "期"}</td>`;
  if (k === "配当10期") return `<td>${spark(v)}${r.配当倍 ? f(r.配当倍, 2) + "倍" : "–"}${r.減配 ? ` <small class="w">減配${r.減配}</small>` : ""}</td>`;
  if (k === "EPS倍") return `<td>${v ? f(v, 2) + "倍" : "–"}</td>`;
  if (k === "BPS倍") return `<td>${v ? f(v, 2) + "倍" : "–"}${r.BPS毎期増 ? '<span class="mk">毎期</span>' : ""}</td>`;
  if (k === "売上成長" || k === "営業利益成長") return `<td>${v === null || v === undefined ? "–" : f(val(v), 1)}</td>`;
  if (k === "株価" || k === "PER" || k === "ROE" || k === "DOE") return `<td>${f(v, 1)}</td>`;
  if (k === "配当利回り" || k === "PBR") return `<td>${f(v, 2)}</td>`;
  if (k === "業種") return `<td style="text-align:left">${v || "–"}</td>`;
  return `<td>${v ?? "–"}</td>`;
}
const SORTKEY = {"配当10期": "配当倍"};
function draw() {
  let rows = D.rows.slice();
  if (sortCol) {
    const key = SORTKEY[sortCol] || sortCol;
    rows.sort((a, b) => {
      let x = val(a[key]), y = val(b[key]);
      if (x === null || x === undefined || typeof x === "string") return 1;
      if (y === null || y === undefined || typeof y === "string") return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
    });
  }
  const head = COLS.map(c => `<th data-c="${c}">${HEAD[c] || c}</th>`).join("");
  const body = rows.map(r => "<tr>" + COLS.map(c => cell(c, r)).join("") + "</tr>").join("");
  document.getElementById("body").innerHTML = `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : ["PER","PBR","PEG"].includes(c);
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
""".replace("__CSS__", CSS).replace("__NAV__", nav("common.html")).replace("__TITLE__", title).replace("__DATA__", data)


if __name__ == "__main__":
    docs = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(docs)
    print(f"作成: {docs / 'index.html'}・{docs / 'common.html'}  {p['mode']} {p['count']}銘柄")
