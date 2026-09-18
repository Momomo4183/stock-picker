# -*- coding: utf-8 -*-
"""①②③の候補リストから、スマホで見るページ（docs/index.html）を作る。

自宅PCで計算 → GitHub に置く → GitHub Pages でスマホから見る、という流れの
「ページを作る」部分。絞り込み（50〜90件 → 10〜20件）の基準はまだ決まって
いないので、現時点では条件に当てはまった全銘柄を並べる。

スーパースクリーナーとの突き合わせ（2026-09-17）で確定した定義を使う。
  PER      実績（trailingPE）。予想PERは取れない銘柄が半分近くあり、②が半分以下になる
  配当利回り 予想（dividendYield）。欠けていて実績が0なら無配として0%
  RSI      ワイルダー方式（単純平均との差は件数にほぼ影響しない）
  信用倍率  売残0の銘柄は除外（含めると③がアプリより多くなる）

使い方:
    python picker/build_site.py [出力先フォルダ]
      既定の出力先は picker/docs
"""
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"

# 条件（本人がスーパースクリーナーに保存しているもの）
SCREENS = [
    {"key": "1", "name": "① 割安・高配当",
     "desc": "PER12以下・PBR1以下・配当利回り3%以上・時価総額700億円以上",
     "aim": "低PER×低PBRで極端な割安をねらう。株価がそこまで上がらなくても高配当で安定して利益を狙う",
     "sort": ("配当利回り%", False)},
    {"key": "2", "name": "② 強い割安",
     "desc": "PER7以下・PBR0.8以下・配当利回り3%未満",
     "aim": "低PER×低PBRで極端な割安をねらう。①よりも株価の上昇を狙う",
     "sort": ("PER", True)},
    {"key": "3", "name": "③ スイング向き",
     "desc": "時価総額300億円以上・信用倍率2.5倍以下・売買代金5百万円以上・25日線乖離0〜1%・RSI25〜60",
     "aim": "これまでの経験からスイングトレードに適していると思われる条件",
     "sort": ("RSI", True)},
]
COLUMNS = ["コード", "銘柄名", "市場", "株価", "PER", "PBR", "配当利回り%",
           "時価総額億", "25日線乖離%", "RSI", "信用倍率", "売買代金20日平均"]


def latest(pattern: str) -> Path:
    files = sorted(glob.glob(str(DATA / pattern)))
    if not files:
        raise FileNotFoundError(f"{pattern} がありません")
    return Path(files[-1])


def rsi_wilder(close: pd.Series, n: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if pd.isna(up) or pd.isna(dn):
        return float("nan")
    return 100.0 if dn == 0 else float(100 - 100 / (1 + up / dn))


def load() -> tuple:
    f_fund, f_px, f_mg = (latest("fundamentals_*.csv"), latest("prices_*.pkl"),
                          latest("margin_*.csv"))
    fund = pd.read_csv(f_fund, dtype={"code": str}, encoding="utf-8-sig")
    rows = []
    for code, d in pd.read_pickle(f_px).items():
        d = d.dropna(subset=["Close"])
        if len(d) < 26:
            continue
        c, v = d["Close"], d["Volume"].fillna(0)
        sma25 = c.rolling(25).mean().iloc[-1]
        rows.append({"code": code, "株価": float(c.iloc[-1]),
                     "終値日": str(d.index[-1].date()),
                     "売買代金20日平均": float((c * v).tail(20).mean()),
                     "25日線乖離%": float((c.iloc[-1] - sma25) / sma25 * 100),
                     "RSI": rsi_wilder(c)})
    px = pd.DataFrame(rows)
    mg = pd.read_csv(f_mg, dtype={"code": str}, encoding="utf-8-sig")[
        ["code", "売残高", "信用倍率"]]
    df = fund.merge(px, on="code", how="left").merge(mg, on="code", how="left")

    # PER・PBR・時価総額・配当利回りは「その日の株価 × 1株あたりの値」で出す。
    # 1株あたりの値（EPS・BPS・株式数・配当）は決算ごとにしか変わらないので、
    # 取り直しは週1回で足りる。毎日取るのは株価だけで済み、取得が1分で終わる。
    # 2026-09-18 検算: yfinance が返す値との一致は PER 99.8% / PBR 99.9% /
    # 時価総額 99.8% が誤差1%以内。配当利回りは基準日の違いで中央値0.9%ずれる。
    price = df["株価"]
    df["PER"] = (price / df["trailingEps"]).where(df["trailingEps"] > 0)
    df["PBR"] = (price / df["bookValue"]).where(df["bookValue"] > 0)
    df["配当利回り%"] = df["dividendRate"] / price * 100
    df["時価総額億"] = price * df["sharesOutstanding"] / 1e8
    # 1株あたりの値が取れていない銘柄は、取得時点の値で埋める
    for col, src in (("PER", "trailingPE"), ("PBR", "priceToBook"),
                     ("配当利回り%", "dividendYield")):
        df[col] = df[col].fillna(df[src])
    df["時価総額億"] = df["時価総額億"].fillna(df["marketCap"] / 1e8)
    no_div = df["配当利回り%"].isna() & (df["trailingAnnualDividendYield"] == 0)
    df.loc[no_div, "配当利回り%"] = 0.0
    df = df.rename(columns={"code": "コード", "name": "銘柄名", "market": "市場"})
    df["市場"] = df["市場"].astype(str).str.replace("（内国株式）", "", regex=False)
    asof = {"株価": str(px["終値日"].max()), "信用残": f_mg.stem.split("_")[-1],
            "財務": f_fund.stem.split("_")[-1]}
    return df, asof


def pick(df: pd.DataFrame, key: str) -> pd.DataFrame:
    per, pbr, div = df["PER"], df["PBR"], df["配当利回り%"]
    cap, rsi = df["時価総額億"], df["RSI"]
    if key == "1":
        m = (per <= 12) & (pbr <= 1) & (div >= 3) & (cap >= 700)
    elif key == "2":
        m = (per <= 7) & (pbr <= 0.8) & (div < 3)
    else:
        m = ((cap >= 300) & (df["信用倍率"] <= 2.5)
             & (df["売買代金20日平均"] >= 5_000_000)
             & (df["25日線乖離%"] >= 0) & (df["25日線乖離%"] <= 1)
             & (rsi >= 25) & (rsi <= 60))
    return df[m.fillna(False)].copy()


def build(out_dir: Path) -> dict:
    df, asof = load()
    lists = []
    for s in SCREENS:
        hit = pick(df, s["key"])
        col, asc = s["sort"]
        hit = hit.sort_values(col, ascending=asc)
        recs = []
        for _, r in hit.iterrows():
            recs.append({c: (None if pd.isna(r.get(c)) else
                             (round(float(r[c]), 2) if isinstance(r.get(c), float)
                              else r.get(c))) for c in COLUMNS})
        lists.append({**{k: s[k] for k in ("key", "name", "desc", "aim")},
                      "count": len(recs), "rows": recs})
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "asof": asof, "universe": len(df), "lists": lists}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "index.html").write_text(render(payload), encoding="utf-8")
    return payload


def render(p: dict) -> str:
    data = json.dumps(p, ensure_ascii=False)
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>銘柄ピックアップ</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 10px}
h1{margin:0;font-size:19px}
.meta{color:var(--sub);font-size:12px;margin-top:4px}
nav{display:flex;gap:6px;padding:0 14px 10px;position:sticky;top:0;background:var(--bg);z-index:2}
nav button{flex:1;padding:10px 4px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:9px;font-size:13px;font-weight:600}
nav button[aria-selected=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
section{padding:0 14px 40px}
.desc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
.desc b{color:var(--ink);font-size:13.5px}
.count{font-size:12px;color:var(--sub);margin:8px 2px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
td:nth-child(2){white-space:normal;min-width:7em}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.empty{padding:24px;text-align:center;color:var(--sub)}
</style></head><body>
<header><h1>銘柄ピックアップ</h1><div class="meta" id="meta"></div></header>
<nav id="tabs"></nav><section id="body"></section>
<script>
const D = __DATA__;
const NUM = {"株価":0,"PER":2,"PBR":2,"配当利回り%":2,"時価総額億":0,"25日線乖離%":2,"RSI":1,"信用倍率":2,"売買代金20日平均":0};
let cur = 0, sortCol = null, sortAsc = true;
document.getElementById("meta").textContent =
  `株価 ${D.asof.株価} 時点 ／ 信用残 ${D.asof.信用残} ／ 対象 ${D.universe.toLocaleString()}銘柄 ／ 作成 ${D.generated}`;
const tabs = document.getElementById("tabs");
D.lists.forEach((l, i) => {
  const b = document.createElement("button");
  b.textContent = l.name.split(" ")[0] + " " + l.count;
  b.onclick = () => { cur = i; sortCol = null; draw(); };
  tabs.appendChild(b);
});
function fmt(k, v) {
  if (v === null || v === undefined) return "–";
  if (typeof v !== "number") return v;
  if (k === "売買代金20日平均") return (v / 1e8).toFixed(2) + "億";
  return v.toLocaleString("ja-JP", {minimumFractionDigits: NUM[k] ?? 0, maximumFractionDigits: NUM[k] ?? 0});
}
function draw() {
  [...tabs.children].forEach((b, i) => b.setAttribute("aria-selected", i === cur));
  const l = D.lists[cur];
  let rows = l.rows.slice();
  if (sortCol) rows.sort((a, b) => {
    const x = a[sortCol], y = b[sortCol];
    if (x === null) return 1; if (y === null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
  });
  const cols = Object.keys(l.rows[0] || {});
  const head = cols.map(c => `<th data-c="${c}">${c.replace("20日平均","")}</th>`).join("");
  const body = rows.map(r => "<tr>" + cols.map(c => `<td>${fmt(c, r[c])}</td>`).join("") + "</tr>").join("");
  document.getElementById("body").innerHTML =
    `<div class="desc"><b>${l.name}</b><br>${l.desc}<br><br>ねらい：${l.aim}</div>
     <div class="count">${l.count} 銘柄（見出しを押すと並べ替え）</div>` +
    (l.count ? `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
             : `<div class="empty">条件に当てはまる銘柄はありません</div>`);
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : true; sortCol = c; draw();
  });
}
draw();
</script></body></html>
""".replace("__DATA__", data)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(out)
    print(f"作成: {out / 'index.html'}")
    print(f"  株価 {p['asof']['株価']} 時点 / 対象 {p['universe']}銘柄")
    for l in p["lists"]:
        print(f"  {l['name']}: {l['count']} 銘柄")
