# -*- coding: utf-8 -*-
"""高配当株を15の指標でチェックするページ（docs/check15.html）を作る。

考え方の出どころ: note「高配当株の15指標」（chem_free、2026-09-25 参照）
    https://note.com/chem_free/n/nebbb338cddeb
高配当株を、成長性・収益性・キャッシュ・財務安全性・割安性・配当の持続性の
6つの観点で見る。絞り込む順番は決めず、まとめて見るという考え方。

このページでの扱い:
  記事に判断の基準がある10指標 … 合否をつけ、「合格数」で並べる
      売上（右肩上がり）・利益（中長期で増加）・営業利益率（5%以上、10%以上は優秀）・
      営業CF（安定してプラス）・自己資本比率（40%以上）・PER（15倍以下）・
      PBR（1倍以下）・配当（中長期で増えているか）・配当性向（70%以上は注意、
      100%超は危険）・利回り（急に高くなっていないか）
  記事に数値の基準が無い4指標 … 値だけ並べる（勝手に基準を作らない）
      ROE・ROA・現金（配当の何年分か）・DOE
  ビジネスモデル … 数字にならないので業種を表示し、判断はご本人に

このページで決めたこと（記事には無い）:
  対象   配当利回り3%以上・時価総額300億円以上
  利益   EPSの代わりに純利益の推移で判定（株式分割で1株あたりの値が飛ぶのを避ける）
  売上   直近が最も古い期より大きく、減収が1回まで
  急上昇 今の利回りが1年前の1.5倍以上なら「急に高くなった」
  金融   銀行・保険・証券・その他金融は、自己資本比率の判定から外す（業態が違う）

使い方:
    python scripts/build_check15.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import dividend_history, load  # noqa: E402
import fetch_statements  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "https://note.com/chem_free/n/nebbb338cddeb"
MIN_YIELD, MIN_CAP = 3.0, 300
FINANCE = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}


def num(v):
    """数値ならfloat、欠けていれば None（NaN をそのまま計算に入れない）。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(v) else v


def latest(s: pd.Series):
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else None


def judge(r: pd.Series, st: pd.DataFrame, dv: dict) -> dict:
    """1銘柄ぶん。各指標は [値, 状態]。状態 g=優秀 p=合格 w=注意 n=対象外。"""
    row = {}
    st = st.sort_values("決算期")

    # 成長性
    rev = st["売上"].dropna()
    if len(rev) >= 3:
        downs = int((rev.diff().dropna() < 0).sum())
        ok = rev.iloc[-1] > rev.iloc[0] and downs <= 1
        row["売上"] = [round((rev.iloc[-1] / rev.iloc[0] - 1) * 100, 1), "p" if ok else "w"]
    ni = st["純利益"].dropna()
    if len(ni) >= 3:
        a, b = ni.iloc[0], ni.iloc[-1]
        ok = b > a and b > 0
        chg = round((b / a - 1) * 100, 1) if a > 0 else None
        row["利益"] = [chg if chg is not None else ("黒字化" if b > 0 else "赤字"),
                       "p" if ok else "w"]

    # 収益性
    op, sales = latest(st["営業利益"]), latest(st["売上"])
    if op is not None and sales:
        m = op / sales * 100
        row["営業利益率"] = [round(m, 1), "g" if m >= 10 else "p" if m >= 5 else "w"]
    net, eq, ta = latest(st["純利益"]), latest(st["純資産"]), latest(st["総資産"])
    if net is not None and eq:
        row["ROE"] = [round(net / eq * 100, 1), ""]
    if net is not None and ta:
        row["ROA"] = [round(net / ta * 100, 1), ""]

    # キャッシュ
    cf = st["営業CF"].dropna()
    if len(cf) >= 2:
        neg = int((cf <= 0).sum())
        row["営業CF"] = ["全期プラス" if neg == 0 else f"マイナス{neg}期",
                         "p" if neg == 0 else "w"]
    cash = latest(st["現金"])
    total_div = (num(r.get("dividendRate")) or 0) * (num(r.get("sharesOutstanding")) or 0)
    if cash is not None and total_div > 0:
        row["現金"] = [round(cash / total_div, 1), ""]

    # 財務安全性
    if eq and ta:
        ratio = eq / ta * 100
        row["自己資本比率"] = [round(ratio, 1),
                             "n" if r.get("sector") in FINANCE else
                             "p" if ratio >= 40 else "w"]

    # 割安性
    if pd.notna(r["PER"]):
        row["PER"] = [round(float(r["PER"]), 1), "p" if r["PER"] <= 15 else "w"]
    if pd.notna(r["PBR"]):
        row["PBR"] = [round(float(r["PBR"]), 2), "p" if r["PBR"] <= 1 else "w"]

    # 配当の持続性
    growth, cuts = dv.get("配当の伸び"), dv.get("減配")
    if growth is not None:
        state = ("g" if growth > 1 and cuts == 0 else "p" if growth > 1 else "w")
        row["配当"] = [round((growth - 1) * 100, 1), state, cuts]
    pr = r.get("配当性向%")
    if pd.notna(pr):
        pr = float(pr)
        row["配当性向"] = [round(pr), "w" if pr > 70 or pr <= 0 else
                          "g" if 30 <= pr <= 60 else "p"]
    bv, dr = num(r.get("bookValue")), num(r.get("dividendRate"))
    if bv and bv > 0 and dr:
        row["DOE"] = [round(dr / bv * 100, 1), ""]
    jump = dv.get("利回り前年比")
    if jump is not None:
        row["急上昇"] = [round(jump, 2), "w" if jump >= 1.5 else "p"]
    return row


SCORED = ["売上", "利益", "営業利益率", "営業CF", "自己資本比率", "PER", "PBR",
          "配当", "配当性向", "急上昇"]
COLUMNS = ["銘柄", "合格", "株価", "配当利回り", "売上", "利益", "営業利益率", "ROE", "ROA",
           "営業CF", "現金", "自己資本比率", "PER", "PBR", "配当", "配当性向", "DOE",
           "急上昇", "業種"]


def build(out_dir: Path) -> dict:
    df, asof = load()
    uni = df[(df["配当利回り%"] >= MIN_YIELD) & (df["時価総額億"] >= MIN_CAP)].copy()
    codes = uni["code"].tolist()
    print(f"対象 {len(codes)}銘柄（配当利回り{MIN_YIELD:g}%以上・時価総額{MIN_CAP}億円以上）",
          flush=True)
    stm = fetch_statements.update(codes)
    stm = stm[stm["error"].fillna("") == ""]
    by_code = {c: g for c, g in stm.groupby("code")}
    print("  配当の履歴を取得中…", flush=True)
    divs = dividend_history(codes)

    rows = []
    empty = pd.DataFrame(columns=["決算期"] + [f[0] for f in fetch_statements.FIELDS])
    for _, r in uni.iterrows():
        j = judge(r, by_code.get(r["code"], empty), divs.get(r["code"], {}))
        scored = [j[k][1] for k in SCORED if k in j and j[k][1] != "n"]
        rec = {"銘柄": f"{r['code']} {r['name']}",
               "合格": [sum(s in ("p", "g") for s in scored), len(scored)],
               "株価": round(float(r["株価"]), 1),
               "配当利回り": round(float(r["配当利回り%"]), 2),
               "業種": r.get("sector") if isinstance(r.get("sector"), str) else None}
        for k in COLUMNS:
            if k not in rec:
                rec[k] = j.get(k)
        rows.append({k: rec.get(k) for k in COLUMNS})
    rows.sort(key=lambda x: (-x["合格"][0], x["合格"][1], -x["配当利回り"]))
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "asof": asof, "count": len(rows), "rows": rows,
               "condition": f"配当利回り{MIN_YIELD:g}%以上・時価総額{MIN_CAP}億円以上",
               "source": SOURCE}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "check15.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "check15.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    data = json.dumps(p, ensure_ascii=False)
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>高配当株 15指標チェック</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 6px}
h1{margin:0;font-size:19px}
.meta{color:var(--sub);font-size:12px;margin-top:4px}
.nav{font-size:12.5px;margin-top:6px}.nav a{color:var(--accent)}
section{padding:6px 14px 40px}
.desc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
.desc b{color:var(--ink)}.desc a{color:var(--accent)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
summary{color:var(--ink);font-weight:600;cursor:pointer}
dl{margin:8px 0 2px}dt{color:var(--ink);font-weight:600;margin-top:6px}dd{margin:0}
.count{font-size:12px;color:var(--sub);margin:8px 2px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:10em;max-width:11.5em}
td:last-child{text-align:left}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.g{color:var(--good);font-weight:700}.p{color:var(--good)}.w{color:var(--warn);font-weight:600}.n{color:var(--sub)}
.score{font-weight:700}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
#toast{position:fixed;left:0;right:0;bottom:18px;margin:0 auto;width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;text-align:center;z-index:10;box-shadow:0 4px 14px #0003}
</style></head><body>
<header><h1>高配当株 15指標チェック</h1><div class="meta" id="meta"></div>
<div class="nav"><a href="./">← 配当株の買い場</a></div></header>
<section>
<div class="desc"><b>対象</b>　<span id="cond"></span><br>
<a id="src" target="_blank" rel="noopener">note「高配当株の15指標」</a>の考え方で、成長性・収益性・キャッシュ・財務安全性・割安性・配当の持続性を並べています。記事に基準がある10指標の<b>合格数</b>の多い順です。<br>
緑＝基準を満たす（太字は特に良い）、橙＝基準に届かない・注意。見出しで並べ替え、<b>銘柄名</b>で楽天証券、<b>コード</b>でコピー。</div>
<details><summary>各列の見方と判定の基準</summary><dl>
<dt>合格</dt><dd>記事に基準がある10指標のうち、満たした数／判定できた数。</dd>
<dt>株価</dt><dd>ページを作ったときに取得した株価（上の「株価 ○月○日 時点」の終値）。</dd>
<dt>売上</dt><dd>最も古い期から直近までの伸び。右肩上がり（直近が最も古い期より大きく、減収が1回まで）なら合格。4〜5期分。</dd>
<dt>利益</dt><dd>記事ではEPS。株式分割で1株あたりの値が飛ぶのを避けるため、純利益の伸びで判定。</dd>
<dt>営業利益率</dt><dd>10%以上は優秀、5%以上で合格、5%未満は注意（記事の基準）。</dd>
<dt>ROE・ROA</dt><dd>記事に数値の基準が無いので値だけ表示。自己資本比率と合わせて見る。</dd>
<dt>営業CF</dt><dd>取得できた全期でプラスなら合格。</dd>
<dt>現金</dt><dd>手元の現金で、今の年間配当の何年分をまかなえるか。値だけ表示。</dd>
<dt>自己資本比率</dt><dd>40%以上で合格（記事の基準）。銀行・保険・証券などは業態が違うので判定から外す（灰色）。</dd>
<dt>PER・PBR</dt><dd>PER15倍以下、PBR1倍以下で合格（記事の基準）。</dd>
<dt>配当</dt><dd>最も古い年から直近の年までの年間配当の伸び（5年）。増えていれば合格、減配なしで増えていれば太字。記念配当の年は多めに出ることがある。</dd>
<dt>配当性向</dt><dd>30〜60%は健全（太字）、70%以下で合格、70%超は注意、100%超は危険（記事の基準）。</dd>
<dt>DOE</dt><dd>純資産に対する配当の割合。値だけ表示。</dd>
<dt>急上昇</dt><dd>今の利回り÷1年前の利回り。1.5倍以上は「急に高くなった」＝株価の急落などが疑われるので注意。</dd>
<dt>業種</dt><dd>ビジネスモデル（景気に左右されやすいか、ストック型かなど）は数字にならないので、業種を手がかりにご自身で判断。</dd>
</dl></details>
<div class="count" id="count"></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span></div>
<script>
const D = __DATA__;
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
const PCT = new Set(["売上","利益","営業利益率","ROE","ROA","自己資本比率","配当","配当性向","DOE"]);
let sortCol = null, sortAsc = false;
document.getElementById("meta").textContent = `株価 ${D.asof.株価} 時点 ／ 作成 ${D.generated}`;
document.getElementById("cond").textContent = D.condition;
document.getElementById("src").href = D.source;
document.getElementById("count").textContent = `${D.count} 銘柄`;
function val(v) { return Array.isArray(v) ? v[0] : v; }
function cell(k, v) {
  if (v === null || v === undefined) return "<td>–</td>";
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button>` +
           `<a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (k === "合格") return `<td class="score">${v[0]}/${v[1]}</td>`;
  if (k === "配当利回り") return `<td>${v.toFixed(2)}</td>`;
  if (k === "株価") return `<td>${v.toLocaleString("ja-JP",{maximumFractionDigits:1})}</td>`;
  if (k === "業種") return `<td>${v}</td>`;
  let [x, s] = v, t;
  if (typeof x !== "number") t = x;
  else if (k === "現金") t = x.toFixed(1) + "年";
  else if (k === "急上昇") t = x.toFixed(2) + "倍";
  else if (k === "PER") t = x.toFixed(1);
  else if (k === "PBR") t = x.toFixed(2);
  else if (PCT.has(k)) t = ((k === "売上" || k === "利益" || k === "配当") && x > 0 ? "+" : "") + x + "%";
  else t = x;
  if (k === "配当" && v[2] > 0) t += ` <small>減配${v[2]}</small>`;
  return `<td class="${s || ""}">${t}</td>`;
}
function draw() {
  let rows = D.rows.slice();
  if (sortCol) rows.sort((a, b) => {
    let x = val(a[sortCol]), y = val(b[sortCol]);
    if (x === null || x === undefined || typeof x === "string") return 1;
    if (y === null || y === undefined || typeof y === "string") return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
  });
  const cols = Object.keys(D.rows[0] || {});
  const head = cols.map(c => `<th data-c="${c}">${c}</th>`).join("");
  const body = rows.map(r => "<tr>" + cols.map(c => cell(c, r[c])).join("") + "</tr>").join("");
  document.getElementById("body").innerHTML =
    `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : ["PER","PBR","配当性向","急上昇"].includes(c);
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
    print(f"作成: {out / 'check15.html'}  {p['count']}銘柄")
    dist = pd.Series([r["合格"][0] for r in p["rows"]]).value_counts().sort_index(ascending=False)
    print("  合格数の分布:", {int(k): int(v) for k, v in dist.items()})
