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


def find_reports(fy_ends: dict, key: str, backs=(5,)) -> dict:
    """銘柄ごとに、最新の有価証券報告書と、その backs 年前の報告書を探す。

    fy_ends: {コード: 直近の決算期末（yfinance の決算書から）}
    返り値: {コード: {"latest": 書類, 5: 書類, ...}}（5年前は "old" でも引ける）
    探す日付は、決算期末の30〜105日後（提出期限は3か月）だけにして、取る量を減らす。
    """
    today = date.today()
    days = set()
    for e in fy_ends.values():
        e = pd.Timestamp(e).date()
        # 1年先は、yfinance が新しい決算をまだ持っていない場合。b-1 は同じく1年ずれた場合
        for y in {0, 1} | {-b for b in backs} | {1 - b for b in backs}:
            base = date(e.year + y, e.month, min(e.day, 28))
            for k in range(30, 106):
                d = base + timedelta(days=k)
                if d <= today and d.weekday() < 5:
                    days.add(d)
    todo = [d for d in sorted(days) if not (DIR / "index" / f"{d:%Y-%m-%d}.json").exists()]
    print(f"  EDINET の提出一覧 {len(days)}日分（新しく取るのは {len(todo)}日分）", flush=True)
    found = {}
    for i, d in enumerate(sorted(days)):
        for x in day_index(d, key):
            found.setdefault(x["secCode"][:4], []).append(x)
        if (i + 1) % 200 == 0:
            print(f"    {i + 1}/{len(days)}", flush=True)
    out = {}
    for code in fy_ends:
        docs = sorted(found.get(code, []), key=lambda x: x["periodEnd"] or "")
        if not docs:
            continue
        latest = docs[-1]
        le = pd.Timestamp(latest["periodEnd"])
        rec = {"latest": latest}
        for b in backs:
            hit = [x for x in docs if abs((pd.Timestamp(x["periodEnd"]) - (le - pd.DateOffset(years=b))).days) <= 45]
            rec[b] = hit[-1] if hit else None
        rec["old"] = rec.get(5)
        out[code] = rec
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
    # IFRS の1株当たり親会社所有者帰属持分は、要素名が EquityToAssetRatioIFRS（名前と中身が違うので注意）
    "BPS": re.compile(r"(?:NetAssetsPerShare|EquityAttributableToOwnersOfParentPerShare|"
                      r"ShareholdersEquityPerShare|EquityToAssetRatioIFRS)\w*SummaryOfBusinessResults$"),
    "DPS": re.compile(r"DividendPaidPerShareSummaryOfBusinessResults$"),
    "売上": re.compile(r"^(?:NetSales|Revenues?|OperatingRevenue\d?|NetSalesIFRS|RevenueIFRS|RevenuesUSGAAP|"
                     r"NetSalesUSGAAP|OperatingRevenueIFRS|TotalRevenues?)SummaryOfBusinessResults$"),
    # 営業利益は主要な経営指標に無い会社が多いので、損益計算書（当期と前期）から取る
    "営業利益": re.compile(r"^(?:OperatingIncome|OperatingProfitLossIFRS|OperatingIncomeLoss|"
                       r"OperatingIncomeLossUSGAAPSummaryOfBusinessResults|"
                       r"OperatingProfitLossIFRSSummaryOfBusinessResults)$"),
}
# 期だけの文脈（セグメント別などの値は使わない）
OFFSET = re.compile(r"^(CurrentYear|Prior(\d)Year)(Duration|Instant)(_NonConsolidatedMember)?$")
PARSER = 5          # parse() の中身を変えたら上げる（保存した解析結果を作り直す）
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
    # 連結決算のある会社は、個別（親会社だけ）の値を使わない。持株会社などは個別の営業利益が
    # 連結と全く違う（2026-10-18 三菱商事: 連結の損益計算書に営業利益が無く、個別の赤字を拾った）
    summ = df[df[eid].str.endswith("SummaryOfBusinessResults", na=False)]
    has_cons = bool((summ[ctx].astype(str) == "CurrentYearDuration").any())
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
            # 主要な経営指標（EPS・BPS・売上など）は連結の無い期だけ個別で補う（連結を始める前の期など）。
            # 営業利益（損益計算書）は、連結のある会社なら個別を使わない
            if has_cons and not consolidated and name == "営業利益":
                continue
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


def parsed(x: dict, key: str):
    """報告書を読んで parse() した結果。書類ごとに保存して使い回す。"""
    f = DIR / "parsed" / f"{x['docID']}.json"
    if f.exists():
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("_v") == PARSER:
            return p
    df = fetch_doc(x["docID"], key)
    if df is None:
        return None
    p = parse(df, x["periodEnd"])
    p["_v"] = PARSER
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return p


NAMES = ("EPS", "BPS", "DPS", "売上", "営業利益")


def ten_years(codes_fy: dict, backs=(5,)) -> dict:
    """銘柄ごとに、10期分の EPS・BPS・DPS・売上・営業利益（調整前）と、言葉の有無、報告書の情報。

    最新と5年前の報告書で10期分（主要な経営指標は5期ずつ載っている）。
    営業利益は損益計算書の2期分しか載らないので、10期そろえるには backs=(2, 4, 5, 6, 8) のように足す。
    """
    key = api_key()
    if not key:
        raise RuntimeError("EDINET のAPIキーがありません（stock-picker/.edinet_key に置いてください）")
    reps = find_reports(codes_fy, key, backs)
    print(f"  有価証券報告書が見つかった銘柄 {len(reps)}/{len(codes_fy)}", flush=True)
    out = {}
    for i, (code, rp) in enumerate(reps.items()):
        rec = {n: {} for n in NAMES}
        rec["src"] = {}
        # 古い報告書から順に読み、新しい報告書の値で上書きする
        for which in sorted(backs, reverse=True) + ["latest"]:
            x = rp.get(which)
            if not x:
                continue
            p = parsed(x, key)
            if p is None:
                continue
            for n in NAMES:
                for fy, v in p.get(n, {}).items():
                    rec[n][fy] = v
                    rec["src"].setdefault(n, {})[fy] = x["submitDateTime"][:10]
            if which == "latest":
                rec["words"], rec["policy"] = p["words"], p["policy"]
                rec["docID"], rec["periodEnd"] = x["docID"], x["periodEnd"]
        out[code] = rec
        if (i + 1) % 100 == 0:
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
