# -*- coding: utf-8 -*-
"""②（高配当・優待の長期保有）の買い場を探すページ（docs/index.html）を作る。

「良い銘柄が安いときがあれば少しずつ増やす」ためのページ。月に1回ほど、
手動で更新して眺める使い方を想定している（2026-09-25 に作り替え）。

候補の条件は、スーパースクリーナーに保存していた①そのまま:
    PER12以下・PBR1以下・配当利回り3%以上・時価総額700億円以上

候補ごとに、長く持つ判断の材料を足す:
    割安度     今の配当利回りが、過去5年の中でどれだけ高いか（100＝最も高い
               ＝配当に対して株価が最も安い）
    減配       過去5年で年間配当が前年を下回った回数
    連続増配   直近まで何年続けて年間配当が増えているか
    配当性向   利益のうち何％を配当に回しているか（高すぎると続けにくい）
    権利月     配当の権利が確定する月
    荒さ       値動きの大きさ（全銘柄の中での位置）。検証で「1年後に−20%以下に
               なっている確率」を下げるのに、期間をまたいで安定して効いた唯一の指標

定義の確認済み事項（2026-09-17 スーパースクリーナーとの突き合わせ）:
    PER は実績。配当利回りは予想（dividendRate ÷ 株価）

株主優待は取得できないので含まない。
**このページは公開されるので、保有銘柄などの個人情報は載せない。**

使い方:
    python scripts/build_site.py [出力先フォルダ]   既定は docs/
"""
import glob
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"

CONDITION = "PER12以下・PBR1以下・配当利回り3%以上・時価総額700億円以上"
COLUMNS = ["銘柄", "割安度", "配当利回り%", "荒さ", "減配", "連続増配",
           "配当性向%", "権利月", "PER", "PBR", "時価総額億", "株価"]


def latest(pattern: str) -> Path:
    files = sorted(glob.glob(str(DATA / pattern)))
    if not files:
        raise FileNotFoundError(f"{pattern} がありません")
    return Path(files[-1])


def atr_pct(d: pd.DataFrame, n: int = 14) -> float:
    c, h, l = d["Close"], d["High"], d["Low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    v = tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1] / c.iloc[-1] * 100
    return float(v) if pd.notna(v) else np.nan


def load() -> tuple:
    f_fund, f_px = latest("fundamentals_*.csv"), latest("prices_*.pkl")
    fund = pd.read_csv(f_fund, dtype={"code": str}, encoding="utf-8-sig")
    rows = []
    for code, d in pd.read_pickle(f_px).items():
        d = d.dropna(subset=["Close"])
        if len(d) < 26:
            continue
        rows.append({"code": code, "株価": float(d["Close"].iloc[-1]),
                     "終値日": str(d.index[-1].date()), "ATR%": atr_pct(d)})
    px = pd.DataFrame(rows)
    # 荒さは全銘柄の中での位置（0＝最も穏やか、100＝最も荒い）
    px["荒さ"] = px["ATR%"].rank(pct=True) * 100
    df = fund.merge(px, on="code", how="left")

    # PER・PBR・時価総額・配当利回りは「その日の株価 × 1株あたりの値」で出す。
    # 2026-09-18 検算: yfinance が返す値との一致は PER 99.8% / PBR 99.9% /
    # 時価総額 99.8% が誤差1%以内。
    price = df["株価"]
    df["PER"] = (price / df["trailingEps"]).where(df["trailingEps"] > 0)
    df["PBR"] = (price / df["bookValue"]).where(df["bookValue"] > 0)
    df["配当利回り%"] = df["dividendRate"] / price * 100
    df["時価総額億"] = price * df["sharesOutstanding"] / 1e8
    for col, src in (("PER", "trailingPE"), ("PBR", "priceToBook"),
                     ("配当利回り%", "dividendYield")):
        df[col] = df[col].fillna(df[src])
    df["時価総額億"] = df["時価総額億"].fillna(df["marketCap"] / 1e8)
    df["配当性向%"] = (df["dividendRate"] / df["trailingEps"] * 100).where(
        df["trailingEps"] > 0)
    asof = {"株価": str(px["終値日"].max()), "財務": f_fund.stem.split("_")[-1]}
    return df, asof


def pick(df: pd.DataFrame) -> pd.DataFrame:
    m = ((df["PER"] <= 12) & (df["PBR"] <= 1) & (df["配当利回り%"] >= 3)
         & (df["時価総額億"] >= 700))
    return df[m.fillna(False)].copy()


def dividend_history(codes: list) -> dict:
    """候補の銘柄だけ、6年分の株価と配当履歴を取って配当の材料を作る。

    株価も配当も yfinance が分割調整済みで返すので、そのまま割り算してよい。
    """
    import yfinance as yf
    out = {}
    if not codes:
        return out
    tks = [f"{c}.T" for c in codes]
    d = yf.download(tks, period="6y", interval="1d", group_by="ticker",
                    actions=True, auto_adjust=False, progress=False,
                    threads=True)
    today = pd.Timestamp.today().normalize()
    for c, tk in zip(codes, tks):
        try:
            sub = d[tk] if len(tks) > 1 else d
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty or "Dividends" not in sub:
            continue
        sub.index = pd.DatetimeIndex(sub.index).tz_localize(None)
        close, dv = sub["Close"], sub["Dividends"].fillna(0)
        rec = {}

        # 割安度: 直近1年の配当 ÷ 株価 を毎週出し、今の値が過去5年の何％点か
        ttm = dv.rolling("365D").sum()
        yld = (ttm / close).resample("W-FRI").last()
        start = today - pd.DateOffset(years=5)
        full = yld[(yld.index >= start)
                   & (yld.index >= close.index[0] + pd.Timedelta(days=365))]
        if len(full) >= 104 and full.iloc[-1] > 0:        # 2年分以上あるとき
            rec["割安度"] = float((full.iloc[:-1] < full.iloc[-1]).mean() * 100)

        # 減配・連続増配: 暦年ごとの配当合計（今年は途中なので使わない）
        paid = dv[dv > 0]
        yearly = paid.groupby(paid.index.year).sum()
        yearly = yearly[yearly.index < today.year].tail(6)
        if len(yearly) >= 3:
            v = yearly.values
            rec["減配"] = int(sum(v[i] < v[i - 1] * 0.97
                                 for i in range(1, len(v))))
            streak = 0
            for i in range(len(v) - 1, 0, -1):
                if v[i] > v[i - 1] * 1.001:
                    streak += 1
                else:
                    break
            rec["連続増配"] = streak

        # 権利月: 直近13か月の権利落ち日の月
        recent = paid[paid.index >= today - pd.DateOffset(months=13)]
        if len(recent):
            rec["権利月"] = "・".join(str(m) for m in
                                      sorted(set(recent.index.month)))
        out[c] = rec
    return out


def build(out_dir: Path) -> dict:
    df, asof = load()
    hit = pick(df)
    hist = dividend_history(hit["code"].tolist())
    recs = []
    for _, r in hit.iterrows():
        h = hist.get(r["code"], {})
        row = {"銘柄": f"{r['code']} {r['name']}", **{
            k: h.get(k) for k in ("割安度", "減配", "連続増配", "権利月")}}
        for c in ("配当利回り%", "荒さ", "配当性向%", "PER", "PBR",
                  "時価総額億", "株価"):
            v = r.get(c)
            row[c] = None if pd.isna(v) else round(float(v), 2)
        if row["割安度"] is not None:
            row["割安度"] = round(row["割安度"])
        recs.append({c: row.get(c) for c in COLUMNS})
    recs.sort(key=lambda x: (x["割安度"] is None, -(x["割安度"] or 0)))
    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "asof": asof, "universe": len(df), "condition": CONDITION,
               "count": len(recs), "rows": recs}
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
<title>配当株の買い場</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--sub:#5d6b78;--line:#e2e7ec;--accent:#0c6f79;--hi:#eef6f6;--good:#0b7a4b;--warn:#b25c00}
@media(prefers-color-scheme:dark){:root{--bg:#0e1419;--card:#161f26;--ink:#e6ecf0;--sub:#9aa9b4;--line:#243039;--accent:#4fb6bf;--hi:#12303350;--good:#4cc38a;--warn:#f0a050}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 14px 6px}
h1{margin:0;font-size:19px}
.meta{color:var(--sub);font-size:12px;margin-top:4px}
section{padding:6px 14px 40px}
.desc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
.desc b{color:var(--ink)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 13px;font-size:12.5px;color:var(--sub);margin-bottom:10px}
summary{color:var(--ink);font-weight:600;cursor:pointer}
dl{margin:8px 0 2px}dt{color:var(--ink);font-weight:600;margin-top:6px}dd{margin:0}
.count{font-size:12px;color:var(--sub);margin:8px 2px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 7px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--hi);color:var(--sub);font-size:11.5px;cursor:pointer;position:sticky;top:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{background:var(--hi);z-index:2}
td:first-child{white-space:normal;min-width:8.5em;max-width:10em}
tbody tr:last-child td{border-bottom:none}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.good{color:var(--good);font-weight:600}.warn{color:var(--warn);font-weight:600}
.empty{padding:24px;text-align:center;color:var(--sub)}
.code{font:inherit;font-size:11.5px;font-weight:600;color:var(--accent);background:var(--hi);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-right:4px;cursor:pointer}
td a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
#toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 14px;font-size:13px;display:none;align-items:center;gap:10px;z-index:10;box-shadow:0 4px 14px #0003;max-width:calc(100% - 32px)}
#toast a{color:var(--bg);font-weight:600;border:1px solid var(--bg);border-radius:7px;padding:4px 9px;text-decoration:none;white-space:nowrap}
</style></head><body>
<header><h1>配当株の買い場</h1><div class="meta" id="meta"></div></header>
<section>
<div class="desc"><b>条件</b>　<span id="cond"></span><br>
並び順は「割安度」の高い順（今の利回りが、その銘柄の過去5年の中で高い＝配当に対して株価が安い）。見出しを押すと並べ替えます。株主優待は含みません。<br>
<b>銘柄名</b>を押すと楽天証券の銘柄ページが開きます。<b>コード</b>を押すとコピーされるので、iSPEEDの検索に貼り付けてください。</div>
<details><summary>各列の見方</summary><dl>
<dt>割安度（0〜100）</dt><dd>今の配当利回りが過去5年の中でどれだけ高いか。100に近いほど、配当に対して株価が安い。</dd>
<dt>荒さ</dt><dd>値動きの大きさ（全銘柄の中での位置）。「穏やか」な銘柄ほど、1年後に大きく値下がりしている確率が低い傾向がありました（過去14年の検証で、前半・後半どちらの期間でも確認）。</dd>
<dt>減配</dt><dd>過去5年で、年間配当が前の年を下回った回数。記念配当の翌年も1回と数えます。</dd>
<dt>連続増配</dt><dd>直近まで何年続けて年間配当が増えているか。</dd>
<dt>配当性向</dt><dd>利益のうち配当に回している割合。100%を超えていると、今の配当を続けるのは難しい。</dd>
<dt>権利月</dt><dd>配当の権利が確定する月（直近1年の実績）。</dd>
</dl></details>
<div class="count" id="count"></div>
<div id="body"></div>
</section>
<div id="toast" role="status"><span id="toastMsg"></span><a href="ispeed://">iSPEEDを開く</a></div>
<script>
const D = __DATA__;
const NUM = {"配当利回り%":2,"配当性向%":0,"PER":1,"PBR":2,"時価総額億":0,"株価":0};
let sortCol = null, sortAsc = false;
document.getElementById("meta").textContent =
  `株価 ${D.asof.株価} 時点 ／ 対象 ${D.universe.toLocaleString()}銘柄 ／ 作成 ${D.generated}`;
document.getElementById("cond").textContent = D.condition;
document.getElementById("count").textContent = `${D.count} 銘柄`;
// 楽天証券の銘柄ページ（ログインなしで株価・チャート・ニュース・企業情報が見られる）
const QUOTE = code => `https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric=${code}.T`;
function cell(k, v) {
  if (v === null || v === undefined) return "<td>–</td>";
  if (k === "銘柄") {
    const i = v.indexOf(" "), code = v.slice(0, i), name = v.slice(i + 1);
    return `<td><button class="code" data-code="${code}">${code}</button>` +
           `<a href="${QUOTE(code)}" target="_blank" rel="noopener">${name}</a></td>`;
  }
  if (k === "荒さ") {
    const t = v < 33 ? ["穏やか","good"] : v < 67 ? ["普通",""] : ["荒い","warn"];
    return `<td class="${t[1]}">${t[0]}</td>`;
  }
  if (k === "割安度") return `<td class="${v >= 80 ? "good" : ""}">${v}</td>`;
  if (k === "減配") return `<td class="${v > 0 ? "warn" : ""}">${v}回</td>`;
  if (k === "連続増配") return `<td class="${v >= 3 ? "good" : ""}">${v}年</td>`;
  if (k === "配当性向%") return `<td class="${v > 100 ? "warn" : ""}">${v.toFixed(0)}</td>`;
  if (typeof v !== "number") return `<td>${v}</td>`;
  return `<td>${v.toLocaleString("ja-JP",{minimumFractionDigits:NUM[k]??0,maximumFractionDigits:NUM[k]??0})}</td>`;
}
function draw() {
  let rows = D.rows.slice();
  if (sortCol) rows.sort((a, b) => {
    const x = a[sortCol], y = b[sortCol];
    if (x === null) return 1; if (y === null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * (sortAsc ? 1 : -1);
  });
  const cols = Object.keys(D.rows[0] || {});
  const head = cols.map(c => `<th data-c="${c}">${c.replace("%","")}</th>`).join("");
  const body = rows.map(r => "<tr>" + cols.map(c => cell(c, r[c])).join("") + "</tr>").join("");
  document.getElementById("body").innerHTML = D.count
    ? `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
    : `<div class="empty">条件に当てはまる銘柄はありません</div>`;
  document.querySelectorAll("th").forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    sortAsc = sortCol === c ? !sortAsc : (c === "荒さ" || c === "減配" || c === "配当性向%" || c === "PER" || c === "PBR");
    sortCol = c; draw();
  });
  document.querySelectorAll(".code").forEach(b => b.onclick = () => copyCode(b.dataset.code));
}
// コードをコピーして、iSPEEDを開くボタンを出す。アプリへの移動は押したときだけ
// （iSPEEDは銘柄を指定して開く方法が公開されていないので、検索に貼り付けてもらう）
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
    ok ? `${code} をコピーしました` : `コピーできませんでした（コード ${code}）`;
  const el = document.getElementById("toast");
  el.style.display = "flex";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 6000);
}
draw();
</script></body></html>
""".replace("__DATA__", data)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    p = build(out)
    print(f"作成: {out / 'index.html'}")
    print(f"  株価 {p['asof']['株価']} 時点 / 対象 {p['universe']}銘柄"
          f" / 候補 {p['count']}銘柄")
