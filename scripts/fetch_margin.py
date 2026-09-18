# -*- coding: utf-8 -*-
"""JPX「銘柄別信用取引週末残高」から信用倍率を作る。

スーパースクリーナー条件③の「信用倍率2.5倍以下」を再現するためのもの。
yfinance には信用残が無い。JPX の日次の「個別銘柄信用取引残高表」は
日々公表銘柄（約330銘柄）だけで全銘柄には使えないため、週次の PDF を読む。

  https://www.jpx.co.jp/markets/statistics-equities/margin/05.html
  （毎週火曜ごろ、前週末の申込み現在の残高を公表）

PDF の並び（1銘柄あたり）:
  区分(B) / 銘柄名 / コード5桁（例 13010 = 1301）/ ISIN（JP + 10文字）/
  売残高 / 前週比 / 買残高 / 前週比 /
  売の内訳（一般・前週比・制度・前週比）/ 買の内訳（一般・前週比・制度・前週比）
ISIN の行を目印にし、その前2行を銘柄名とコード、後ろ12行を数値として読む。
「▲」は負数。

信用倍率 = 買残高 ÷ 売残高（合計）。売残高が0の銘柄は倍率を出せない（空欄）。

使い方:
    python picker/fetch_margin.py
      → data/margin_YYYYMMDD.csv（YYYYMMDD は申込み現在の日付）
"""
import io
import re
import urllib.request
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"
PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"
UA = {"User-Agent": "Mozilla/5.0"}
ISIN = re.compile(r"^JP[0-9A-Z]{10}$")
CODE5 = re.compile(r"^[0-9A-Z]{4}0$")
NUM_FIELDS = ["売残高", "売残高_前週比", "買残高", "買残高_前週比",
              "売_一般", "売_一般_前週比", "売_制度", "売_制度_前週比",
              "買_一般", "買_一般_前週比", "買_制度", "買_制度_前週比"]


def _get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=90).read()


def _num(text: str):
    t = text.replace(",", "").replace(" ", "").replace("　", "")
    neg = t.startswith("▲")
    t = t.lstrip("▲")
    if t in ("", "-", "－"):
        return 0
    try:
        v = int(t)
    except ValueError:
        return None
    return -v if neg else v


def latest_pdf_url() -> str:
    html = _get(PAGE).decode("utf-8", "replace")
    pdfs = re.findall(r'href="([^"]*syumatsu(\d{8})00\.pdf)"', html)
    if not pdfs:
        raise RuntimeError(f"週末残高の PDF が見つかりません: {PAGE}")
    href, _ = max(pdfs, key=lambda x: x[1])
    return "https://www.jpx.co.jp" + href if href.startswith("/") else href


def parse(pdf_bytes: bytes) -> pd.DataFrame:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rows = []
    for page in doc:
        lines = [l.strip() for l in page.get_text("text").splitlines()
                 if l.strip()]
        for i, line in enumerate(lines):
            if not ISIN.match(line) or i < 2 or i + 12 >= len(lines):
                continue
            code5, name = lines[i - 1], lines[i - 2]
            if not CODE5.match(code5):
                continue
            nums = [_num(x) for x in lines[i + 1:i + 13]]
            if any(v is None for v in nums):
                continue
            row = {"code": code5[:4], "name": name.replace("　普通株式", ""),
                   "isin": line}
            row.update(dict(zip(NUM_FIELDS, nums)))
            rows.append(row)
    df = pd.DataFrame(rows).drop_duplicates("code")
    df["信用倍率"] = df.apply(
        lambda r: round(r["買残高"] / r["売残高"], 2) if r["売残高"] > 0
        else None, axis=1)
    return df


def main() -> int:
    DATA.mkdir(exist_ok=True)
    url = latest_pdf_url()
    asof = re.search(r"syumatsu(\d{8})00", url).group(1)
    print(f"取得: {url}")
    df = parse(_get(url))
    out = DATA / f"margin_{asof}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"保存: {out.name}  {len(df)}銘柄"
          f"（売残0で倍率なし {int(df['信用倍率'].isna().sum())}銘柄）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
