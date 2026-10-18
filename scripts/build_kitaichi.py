# -*- coding: utf-8 -*-
"""期待値投資のページ（docs/kitaichi.html）を作る。

2026-10-18 ご本人が示した条件:
  スクリーニング  配当利回り2.5%以上・配当性向50%以下・売上高10期連続増加・
                  営業利益が10期で増加傾向（減益の期があってもよい）
  確認項目        過去のPERの変化幅（例: PER8〜12）と、今のPERでの売買の目安
                  （幅の真ん中より下なら買い、上なら売りの目安）。PERの変化を簡単なグラフで

このページで決めたこと:
  配当利回り・配当性向  ほかのページと同じ（予想配当÷株価、予想配当÷実績EPS）
  売上高10期連続増加    11期分の売上で、10回続けて前期より増えた（有価証券報告書の主要な経営指標）
  営業利益の増加傾向    10期分で、直近が9期前より多く、10期をならした傾き（回帰直線）が右上がり
                        （有価証券報告書の連結損益計算書。1冊に2期分なので5冊で10期）
  PERの変化幅           過去10年の毎月の PER（月末の株価÷その時点で発表済みの直近の通期EPS）の
                        下から1割〜上から1割の範囲。真ん中は中央値。EPSが赤字の月は除く
                        （決算発表は期末の約3か月後として扱う）
  今のPER               今の株価÷直近の通期EPS（グラフと同じ物差しにそろえる）
  売買の目安            今のPERが中央値以下なら「買い」、上なら「売り」

使い方:
    python scripts/build_kitaichi.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load  # noqa: E402
from build_renzoku import actions_for, adjust  # noqa: E402
import fetch_edinet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAV = [("./", "トップ"), ("check15.html", "高配当株 15指標チェック"), ("growth.html", "グロース株の候補"),
       ("renzoku.html", "連続増配株"), ("kitaichi.html", "期待値投資"), ("common.html", "3つに共通する銘柄")]
MIN_YIELD, MAX_PAYOUT = 2.5, 50


def fy_ends() -> pd.Series:
    st = pd.read_csv(ROOT / "data" / "statements.csv", dtype={"code": str})
    st = st[st["error"].fillna("") == ""]
    return st.sort_values("決算期").groupby("code").tail(1).set_index("code")["決算期"]


def sales_streak(s: dict) -> int:
    """直近から何回続けて前期より売上が増えたか。"""
    v = [s[k] for k in sorted(s)]
    n = 0
    for i in range(len(v) - 1, 0, -1):
        if v[i] > v[i - 1]:
            n += 1
        else:
            break
    return n


def op_trend(o: dict):
    """(条件を満たすか, 10期分の値, 減益の回数, 9期前に対する倍率)"""
    keys = sorted(o)[-10:]
    v = [o[k] for k in keys]
    if len(v) < 10:
        return False, v, None, None
    slope = np.polyfit(range(10), v, 1)[0]
    cuts = sum(v[i] < v[i - 1] for i in range(1, 10))
    ratio = v[-1] / v[0] if v[0] > 0 else None
    return bool(v[-1] > v[0] and slope > 0), v, cuts, ratio


def monthly_prices(codes: list) -> dict:
    import yfinance as yf
    out = {}
    tks = [f"{c}.T" for c in codes]
    for i in range(0, len(tks), 100):
        chunk = tks[i:i + 100]
        d = yf.download(chunk, period="11y", interval="1mo", auto_adjust=False, progress=False,
                        group_by="ticker", threads=True)
        for tk in chunk:
            try:
                s = (d[tk] if len(chunk) > 1 else d)["Close"].dropna()
            except KeyError:
                continue
            s.index = pd.DatetimeIndex(s.index).tz_localize(None)
            out[tk[:-2]] = s
    return out


def per_band(close: pd.Series, a: dict, price_now: float):
    """毎月の PER と、その幅（下から1割・中央値・上から1割）、今の PER。"""
    eps = pd.Series(a["EPS"], index=[(pd.Timestamp(fy + "-01") + pd.offsets.MonthEnd(0) + pd.DateOffset(months=3))
                                     for fy in a["fy"]]).sort_index()
    known = eps.reindex(close.index.union(eps.index)).ffill().reindex(close.index)
    per = (close / known).where(known > 0).dropna()
    per = per[per.index >= close.index[-1] - pd.DateOffset(years=10)]
    if len(per) < 36 or a["EPS"][-1] <= 0:
        return None
    lo, mid, hi = (float(per.quantile(q)) for q in (0.1, 0.5, 0.9))
    now = price_now / a["EPS"][-1]
    return {"lo": round(lo, 1), "mid": round(mid, 1), "hi": round(hi, 1), "now": round(now, 1),
            "pos": round((now - lo) / (hi - lo) * 100) if hi > lo else None,
            "series": [[d.strftime("%Y-%m"), round(float(v), 1)] for d, v in per.items()]}


def build(out_dir: Path) -> dict:
    df, asof = load()
    ends = fy_ends()
    u = df[(df["配当利回り%"] >= MIN_YIELD) & (df["配当性向%"] > 0) & (df["配当性向%"] <= MAX_PAYOUT)
           & df["code"].isin(ends.index)].copy()
    print(f"配当利回り{MIN_YIELD}%以上・配当性向{MAX_PAYOUT}%以下 {len(u)}銘柄", flush=True)
    # 1回目: 最新と5年前の報告書（売上10期）で、売上がずっと伸びている銘柄に絞る
    raw = fetch_edinet.ten_years({c: ends[c] for c in u["code"]})
    c1 = [c for c, r in raw.items() if len(r["売上"]) >= 10 and sales_streak(r["売上"]) >= 9]
    print(f"  売上が10期ずっと伸びている {len(c1)}銘柄。営業利益と11期目の売上を取りに行きます", flush=True)
    # 2回目: 2・4・6・8年前の報告書も読み、営業利益10期と売上11期以上をそろえる
    raw2 = fetch_edinet.ten_years({c: ends[c] for c in c1}, backs=(2, 4, 5, 6, 8))
    act = actions_for(c1)
    picks = []
    for c in c1:
        r = raw2.get(c)
        if not r or sales_streak(r["売上"]) < 10:
            continue
        ok, opv, cuts, ratio = op_trend(r["営業利益"])
        if not ok:
            continue
        picks.append((c, r, opv, cuts, ratio))
    print(f"  売上10期連続増加・営業利益が増加傾向 {len(picks)}銘柄", flush=True)
    px = monthly_prices([p[0] for p in picks])
    info = u.set_index("code")
    rows = []
    for c, r, opv, cuts, ratio in picks:
        a = adjust(r, act.get(c, {}))
        x = info.loc[c]
        band = per_band(px[c], a, float(x["株価"])) if c in px and a else None
        sales = [r["売上"][k] for k in sorted(r["売上"])][-11:]
        rows.append({
            "銘柄": f"{c} {x['name']}",
            "目安": None if not band else ("買い" if band["now"] <= band["mid"] else "売り"),
            "PER": band,
            "株価": round(float(x["株価"]), 1),
            "配当利回り": round(float(x["配当利回り%"]), 2),
            "配当性向": round(float(x["配当性向%"])),
            "売上": [round(v / 1e8, 1) for v in sales],
            "売上倍": round(sales[-1] / sales[0], 2),
            "増収": sales_streak(r["売上"]),
            "営業利益": [round(v / 1e8, 1) for v in opv],
            "営業利益倍": round(ratio, 2) if ratio else None,
            "減益": cuts,
            "時価総額": round(float(x["時価総額億"])),
            "業種": x.get("sector") if isinstance(x.get("sector"), str) else None,
        })
    rows.sort(key=lambda z: (z["目安"] != "買い", z["PER"]["pos"] if z["PER"] and z["PER"]["pos"] is not None else 999))
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "asof": asof, "count": len(rows),
               "universe": len(u), "sales10": len(c1), "rows": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kitaichi.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "kitaichi.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    nav = '<div class="nav">' + "".join(f'<a href="{h}">{t}</a>' for h, t in NAV if h != "kitaichi.html") + "</div>"
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>期待値投資</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00;--band:#0c6f7922}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050;--band:#4fb6bf2e}}
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
.count{font-size:12px;color:var(--sub);margin:8px 2px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:10em;max-width:11.5em}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.buy{color:var(--good);font-weight:700}.sell{color:var(--warn);font-weight:700}.s{color:var(--sub)}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
svg{vertical-align:middle;display:inline-block}
.chartbtn{background:none;border:0;padding:0;cursor:pointer;color:var(--accent)}
tr.detail td{white-space:normal;text-align:left;background:var(--hi);position:static}
.big{width:100%;max-width:640px;height:auto}
.legend{font-size:11.5px;color:var(--sub)}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>期待値投資</h1><div class="meta" id="meta"></div>
__NAV__</header>
<section>
<div class="desc"><b>条件</b>　配当利回り2.5%以上・配当性向50%以下・売上高10期連続増加・営業利益が10期で増加傾向（減益の期があってもよい）<br>
<b>確認</b>　過去10年のPERの幅（下から1割〜上から1割）と、今のPERがその中のどこにあるか。幅の真ん中（中央値）より下なら<b class="buy">買い</b>、上なら<b class="sell">売り</b>の目安です。<br>
グラフを押すと大きく表示。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー。</div>
<details><summary>各列の見方</summary><dl>
<dt>目安・位置</dt><dd>今のPERが過去10年の幅のどこにあるか（0%＝幅の下端、100%＝上端。0未満・100超は幅の外）。中央値以下で「買い」、上で「売り」。</dd>
<dt>PER（今・幅）</dt><dd>今のPER＝今の株価÷直近の通期EPS。幅は過去10年の毎月のPER（月末の株価÷その時点で発表済みの通期EPS）の下から1割〜上から1割、真ん中は中央値。EPSが赤字の月は除く。</dd>
<dt>PERのグラフ</dt><dd>線＝毎月のPER、帯＝幅（下から1割〜上から1割）、点線＝中央値、点＝今。</dd>
<dt>売上・営業利益</dt><dd>有価証券報告書の連結の値（億円）。売上は11期分で10回続けて増収。営業利益は10期分で、直近が9期前より多く、10期をならした傾きが右上がり。減益の回数も表示。</dd>
<dt>注意</dt><dd>会計基準の変更（2021年度からの収益認識基準など）で売上の数字が変わり、連続増収が途切れて見える会社があります。PERの幅は過去の話で、同じ幅に戻る保証はありません。</dd>
</dl></details>
<div class="count" id="count"></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const COLS = ["銘柄","目安","PER今","PER幅","グラフ","株価","配当利回り","配当性向","売上","営業利益","時価総額","業種"];
const HEAD = {"PER今":"今のPER","PER幅":"PERの幅（中央）","グラフ":"PERの推移（10年）","配当利回り":"利回り%","配当性向":"配当性向%","売上":"売上（11期）","営業利益":"営業利益（10期）","時価総額":"時価総額億"};
const KEY = {"目安": r => r.PER ? r.PER.pos : null, "PER今": r => r.PER ? r.PER.now : null, "PER幅": r => r.PER ? r.PER.mid : null,
             "売上": r => r.売上倍, "営業利益": r => r.営業利益倍};
let sortCol = null, sortAsc = true, open = new Set();
document.getElementById("meta").textContent = `株価 ${D.asof.株価} 時点 ／ 作成 ${D.generated}`;
document.getElementById("count").textContent = `${D.count} 銘柄（配当の条件を満たす ${D.universe} 銘柄 → 売上が10期伸び続けている ${D.sales10} 銘柄 → すべての条件）`;
const f = (x, d) => x === null || x === undefined ? "–" : Number(x).toLocaleString("ja-JP", {minimumFractionDigits: d, maximumFractionDigits: d});
function spark(v) {
  if (!v || v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), w = 54, h = 16;
  const pts = v.map((x, i) => [i * w / (v.length - 1), h - 1 - (hi > lo ? (x - lo) / (hi - lo) * (h - 2) : (h - 2) / 2)]);
  return `<svg width="${w}" height="${h}"><polyline fill="none" stroke="currentColor" stroke-width="1.4" points="${pts.map(p => p.join(",")).join(" ")}"/></svg> `;
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
    for (const [v, t] of [[b.hi, "上 " + b.hi], [b.mid, "中 " + b.mid], [b.lo, "下 " + b.lo]])
      g += `<text x="${padL - 4}" y="${Y(v) + 4}" font-size="10" text-anchor="end" fill="var(--sub)">${v}</text>`;
    let last = "";
    s.forEach((x, i) => { const y = x[0].slice(0, 4); if (y !== last && x[0].endsWith("-01")) { g += `<text x="${X(i)}" y="${h - 4}" font-size="10" text-anchor="middle" fill="var(--sub)">${y}</text>`; } last = y; });
    g += `<text x="${X(s.length)}" y="${Y(b.now) - 7}" font-size="10" text-anchor="end" fill="var(--ink)">今 ${b.now}</text>`;
  }
  return g + "</svg>";
}
function cell(k, r) {
  const b = r.PER;
  if (k === "銘柄") {
    const v = r.銘柄, i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button><a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (!b && ["目安","PER今","PER幅","グラフ"].includes(k)) return `<td class="s">–</td>`;
  if (k === "目安") return `<td><span class="${r.目安 === "買い" ? "buy" : "sell"}">${r.目安}</span> <small class="s">${b.pos}%</small></td>`;
  if (k === "PER今") return `<td>${f(b.now, 1)}</td>`;
  if (k === "PER幅") return `<td>${f(b.lo, 1)}〜${f(b.hi, 1)} <small class="s">（${f(b.mid, 1)}）</small></td>`;
  if (k === "グラフ") return `<td><button class="chartbtn" data-c="${r.銘柄}" aria-label="グラフを大きく">${perChart(b, 120, 34, false)}</button></td>`;
  if (k === "株価") return `<td>${f(r.株価, 1)}</td>`;
  if (k === "配当利回り") return `<td>${f(r.配当利回り, 2)}</td>`;
  if (k === "配当性向") return `<td>${f(r.配当性向, 0)}</td>`;
  if (k === "売上") return `<td>${spark(r.売上)}${f(r.売上倍, 2)}倍</td>`;
  if (k === "営業利益") return `<td>${spark(r.営業利益)}${r.営業利益倍 ? f(r.営業利益倍, 2) + "倍" : "–"}${r.減益 ? ` <small class="s">減益${r.減益}</small>` : ""}</td>`;
  if (k === "時価総額") return `<td>${f(r.時価総額, 0)}</td>`;
  if (k === "業種") return `<td style="text-align:left">${r.業種 || "–"}</td>`;
  return "<td>–</td>";
}
function draw() {
  let rows = D.rows.slice();
  if (sortCol) {
    const get = KEY[sortCol] || (r => r[sortCol]);
    rows.sort((a, b) => {
      const x = get(a), y = get(b);
      if (x === null || x === undefined || typeof x === "string") return 1;
      if (y === null || y === undefined || typeof y === "string") return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
    });
  }
  const head = COLS.map(c => `<th data-c="${c}">${HEAD[c] || c}</th>`).join("");
  const body = rows.map(r => {
    let h = "<tr>" + COLS.map(c => cell(c, r)).join("") + "</tr>";
    if (open.has(r.銘柄) && r.PER) h += `<tr class="detail"><td colspan="${COLS.length}"><div class="legend">${r.銘柄}　PER の推移（月末）。帯＝過去10年の幅 ${r.PER.lo}〜${r.PER.hi}、点線＝中央値 ${r.PER.mid}、点＝今 ${r.PER.now}</div>${perChart(r.PER, 640, 170, true)}</td></tr>`;
    return h;
  }).join("");
  document.getElementById("body").innerHTML = `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : ["目安","PER今","PER幅"].includes(c);
    sortCol = c; draw();
  });
  document.querySelectorAll(".code").forEach(b => b.onclick = () => copyCode(b.dataset.code));
  document.querySelectorAll(".chartbtn").forEach(b => b.onclick = () => { open.has(b.dataset.c) ? open.delete(b.dataset.c) : open.add(b.dataset.c); draw(); });
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
""".replace("__NAV__", nav).replace("__DATA__", json.dumps(p, ensure_ascii=False))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(out)
    print(f"作成: {out / 'kitaichi.html'}  {p['count']}銘柄（配当の条件 {p['universe']} → 売上10期 {p['sales10']}）")
