# -*- coding: utf-8 -*-
"""EDINET（金融庁）の有価証券報告書から、過去10期の 1株あたり利益・純資産・配当と、
配当方針の文章を取る（連続増配株のページで使う）。

yfinance の決算書は4〜5期分しかないので、10期分はここから取る。
有価証券報告書の「主要な経営指標等の推移」には5期分が載っているので、
最新の報告書と5年前の報告書の2つで10期になる。

APIキーが要る（無料。ご本人が EDINET で登録して発行する）。キーは次のどちらかに置く:
    stock-picker/.edinet_key というファイル（1行。.gitignore 済みで GitHub には上げない）
    環境変数 EDINET_API_KEY

取ったものは data/edinet/ に保存して使い回す:
    index/日付.json   その日に出た有価証券報告書の一覧（過去の日付は変わらないので取り直さない）
    docs/書類ID.zip   報告書のCSV（一度取れば取り直さない）

使い方（単体で試すとき）:
    python scripts/fetch_edinet.py 7203 8058
"""
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "edinet"
API = "https://api.edinet-fsa.go.jp/api/v2"
PAUSE = 0.3                       # 1回ごとに少し待つ（相手に負担をかけない）
YUHO = "120"                      # 有価証券報告書の書類コード


def api_key():
    k = os.environ.get("EDINET_API_KEY")
    f = ROOT / ".edinet_key"
    if not k and f.exists():
        k = f.read_text(encoding="utf-8").strip()
    return k or None


def _get(url: str, params: dict, tries: int = 3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=60)
            time.sleep(PAUSE)
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403):
                raise RuntimeError("EDINET のAPIキーが正しくないか、まだ使えません")
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    return None


def day_index(d: date, key: str) -> list:
    """その日に提出された有価証券報告書の一覧。"""
    f = DIR / "index" / f"{d:%Y-%m-%d}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    r = _get(f"{API}/documents.json", {"date": f"{d:%Y-%m-%d}", "type": 2, "Subscription-Key": key})
    if r is None:
        return []
    keep = []
    for x in r.json().get("results") or []:
        if x.get("docTypeCode") == YUHO and x.get("secCode") and x.get("withdrawalStatus") == "0":
            keep.append({k: x.get(k) for k in ("docID", "secCode", "periodStart", "periodEnd",
                                               "submitDateTime", "csvFlag", "filerName")})
    if d < date.today() - timedelta(days=3):          # 最近の日付はあとで増えることがあるので保存しない
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    return keep


def find_reports(fy_ends: dict, key: str) -> dict:
    """銘柄ごとに、最新の有価証券報告書と、その5年前の報告書を探す。

    fy_ends: {コード: 直近の決算期末（yfinance の決算書から）}
    探す日付は、決算期末の30〜105日後（提出期限は3か月）だけにして、取る量を減らす。
    """
    today = date.today()
    days = set()
    for e in fy_ends.values():
        e = pd.Timestamp(e).date()
        for y in (0, 1, -5, -4):                    # 1年先は、yfinance が新しい決算をまだ持っていない場合
            base = date(e.year + y, e.month, min(e.day, 28))
            for k in range(30, 106):
                d = base + timedelta(days=k)
                if d <= today and d.weekday() < 5:
                    days.add(d)
    print(f"  EDINET の提出一覧 {len(days)}日分（保存済みは取り直さない）", flush=True)
    found = {}
    for i, d in enumerate(sorted(days)):
        for x in day_index(d, key):
            found.setdefault(x["secCode"][:4], []).append(x)
        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{len(days)}", flush=True)
    out = {}
    for code in fy_ends:
        docs = sorted(found.get(code, []), key=lambda x: x["periodEnd"] or "")
        if not docs:
            continue
        latest = docs[-1]
        le = pd.Timestamp(latest["periodEnd"])
        old = [x for x in docs if abs((pd.Timestamp(x["periodEnd"]) - (le - pd.DateOffset(years=5))).days) <= 45]
        out[code] = {"latest": latest, "old": old[-1] if old else None}
    return out


def fetch_doc(doc_id: str, key: str):
    """報告書のCSV（XBRL を CSV にしたもの）の中身を表で返す。"""
    f = DIR / "docs" / f"{doc_id}.zip"
    if not f.exists():
        r = _get(f"{API}/documents/{doc_id}", {"type": 5, "Subscription-Key": key})
        if r is None or not r.content.startswith(b"PK"):
            return None
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(r.content)
    with zipfile.ZipFile(f) as z:
        names = [n for n in z.namelist() if n.endswith(".csv") and "/jpcrp" in n.replace("\\", "/")]
        if not names:
            names = [n for n in z.namelist() if n.endswith(".csv") and "jpaud" not in n]
        if not names:
            return None
        raw = z.read(names[0])
    return pd.read_csv(io.BytesIO(raw), sep="\t", encoding="utf-16", dtype=str)


# 主要な経営指標等の推移（5期分）の要素。日本基準・IFRS・米国基準で名前が違う
PATTERNS = {
    "EPS": re.compile(r"BasicEarningsLossPerShare\w*SummaryOfBusinessResults$"),
    "BPS": re.compile(r"(?:NetAssetsPerShare|EquityAttributableToOwnersOfParentPerShare|"
                      r"ShareholdersEquityPerShare)\w*SummaryOfBusinessResults$"),
    "DPS": re.compile(r"DividendPaidPerShareSummaryOfBusinessResults$"),
}
OFFSET = re.compile(r"^(CurrentYear|Prior(\d)Year)(Duration|Instant)")
# 累進配当・DOE の記載。同じ言葉が別の意味で出ることがある（例: 米国エネルギー省 DOE）ので、
# 近く（前後40字）に「配当」「還元」が無いものは数えない。全角英字は半角にそろえてから探す
KEYWORDS = {"累進配当": re.compile(r"累進"),
            "DOE": re.compile(r"(?<![A-Za-z])DOE(?![A-Za-z])|株主資本配当率|自己資本配当率|純資産配当率")}
NEAR = re.compile(r"配当|還元")


def mentions(text: str, pat) -> bool:
    for m in pat.finditer(text):
        if NEAR.search(text[max(0, m.start() - 40):m.end() + 40]):
            return True
    return False


def parse(df: pd.DataFrame, period_end: str) -> dict:
    """{"EPS": {決算期末: 値}, ...} と、配当方針などの文章に出てくる言葉。"""
    cols = list(df.columns)
    eid, ctx, val = cols[0], cols[2], cols[-1]
    pe = pd.Timestamp(period_end)
    res = {}
    for name, pat in PATTERNS.items():
        sub = df[df[eid].str.split(":").str[-1].str.contains(pat, na=False)]
        best = {}
        for _, r in sub.iterrows():
            m = OFFSET.match(str(r[ctx]))
            if not m:
                continue
            k = 0 if m.group(1) == "CurrentYear" else int(m.group(2))
            try:
                v = float(str(r[val]).replace(",", ""))
            except ValueError:
                continue
            consolidated = "NonConsolidated" not in str(r[ctx])
            fy = (pe - pd.DateOffset(years=k)).strftime("%Y-%m")
            # 連結があれば連結、無ければ個別。配当は個別にしか載らないことが多い
            rank = 1 if consolidated else 0
            if fy not in best or rank > best[fy][0]:
                best[fy] = (rank, v)
        res[name] = {fy: v for fy, (_, v) in best.items()}
    text = unicodedata.normalize("NFKC", " ".join(df[df[eid].str.endswith("TextBlock", na=False)][val].fillna("").tolist()))
    res["words"] = {k: mentions(text, p) for k, p in KEYWORDS.items()}
    # 配当方針の文章（ページで少し見せる）
    pol = df[df[eid].str.endswith("DividendPolicyTextBlock", na=False)][val].fillna("")
    res["policy"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", " ".join(pol.tolist()))).strip()[:400]
    return res


def ten_years(codes_fy: dict) -> dict:
    """銘柄ごとに、10期分の EPS・BPS・DPS（調整前）と、言葉の有無、報告書の情報。"""
    key = api_key()
    if not key:
        raise RuntimeError("EDINET のAPIキーがありません（stock-picker/.edinet_key に置いてください）")
    reps = find_reports(codes_fy, key)
    print(f"  有価証券報告書が見つかった銘柄 {len(reps)}/{len(codes_fy)}", flush=True)
    out = {}
    for i, (code, rp) in enumerate(reps.items()):
        rec = {"EPS": {}, "BPS": {}, "DPS": {}, "src": {}}
        for which in ("old", "latest"):                 # 新しい報告書の値で上書きする
            x = rp.get(which)
            if not x:
                continue
            df = fetch_doc(x["docID"], key)
            if df is None:
                continue
            p = parse(df, x["periodEnd"])
            for n in ("EPS", "BPS", "DPS"):
                for fy, v in p[n].items():
                    rec[n][fy] = v
                    rec["src"].setdefault(n, {})[fy] = x["submitDateTime"][:10]
            if which == "latest":
                rec["words"], rec["policy"] = p["words"], p["policy"]
                rec["docID"], rec["periodEnd"] = x["docID"], x["periodEnd"]
        out[code] = rec
        if (i + 1) % 50 == 0:
            print(f"    報告書 {i + 1}/{len(reps)}", flush=True)
    return out


if __name__ == "__main__":
    st = pd.read_csv(ROOT / "data" / "statements.csv")
    st = st[st["error"].fillna("") == ""]
    lat = st.sort_values("決算期").groupby("code").tail(1).set_index("code")["決算期"]
    lat.index = lat.index.astype(str)
    codes = sys.argv[1:] or ["7203"]
    r = ten_years({c: lat[c] for c in codes if c in lat.index})
    print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])
