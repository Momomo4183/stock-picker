# -*- coding: utf-8 -*-
"""1日1回の更新をまとめて行う。

  1. 株価を取り直す（全銘柄・約1分）
  2. 財務（1株あたりの値）が古ければ取り直す（週1回・遅い）
  3. 信用残が古ければ JPX の週末残高PDFを取り直す（週1回）
  4. ページを作り直す（docs/index.html）
  5. GitHub に反映する（変化があったときだけ）

株価だけ毎日取ればよいのは、PER・PBR・時価総額・配当利回りを
「その日の株価 × 1株あたりの値」で出しているため。

使い方:
    python scripts/update.py            通常（毎日これを実行する）
    python scripts/update.py --full     財務も必ず取り直す
    python scripts/update.py --no-push  GitHub に反映しない（手元で確認するとき）
"""
import datetime as dt
import glob
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"
FUND_MAX_AGE_DAYS = 7      # 1株あたりの値は決算ごとにしか変わらない
MARGIN_MAX_AGE_DAYS = 7    # JPX の週末残高は週1回の公表


def run(cmd: list, timeout: int = 3600) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), timeout=timeout)


def age_days(pattern: str):
    """data/ にある最新ファイルの日付が何日前か。無ければ None。"""
    files = sorted(glob.glob(str(DATA / pattern)))
    if not files:
        return None
    m = re.search(r"(\d{8})", Path(files[-1]).stem)
    if not m:
        return None
    d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    return (dt.date.today() - d).days


def git(*args, check: bool = False) -> str:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} が失敗: {r.stderr.strip()[:200]}")
    return (r.stdout or "").strip()


def main() -> int:
    full = "--full" in sys.argv
    no_push = "--no-push" in sys.argv
    started = dt.datetime.now()
    print("=" * 56)
    print(f"  銘柄ピックアップ 更新  {started:%Y-%m-%d %H:%M:%S}")
    print("=" * 56)
    DATA.mkdir(exist_ok=True)
    py = [sys.executable, "-u"]

    fund_age = age_days("fundamentals_*.csv")
    if full or fund_age is None or fund_age >= FUND_MAX_AGE_DAYS:
        why = "指定" if full else ("無い" if fund_age is None else f"{fund_age}日前")
        print(f"\n[1/4] 財務（1株あたりの値）を取り直します（{why}）")
        if run(py + [str(BASE / "fetch_data.py"), "--fundamentals-only"]) == 0:
            # 取得制限で失敗した銘柄を1社ずつ取り直す
            run(py + [str(BASE / "retry_fundamentals.py"), "--pause", "1.0"])
    else:
        print(f"\n[1/4] 財務は{fund_age}日前のものを使います（取り直しません）")

    print("\n[2/4] 株価を取り直します")
    if run(py + [str(BASE / "fetch_data.py"), "--prices-only"]) != 0:
        print("  [NG] 株価が取れませんでした。ページは作り直しません。")
        return 1

    mg_age = age_days("margin_*.csv")
    if mg_age is None or mg_age >= MARGIN_MAX_AGE_DAYS:
        print(f"\n[3/4] 信用残を取り直します（{'無い' if mg_age is None else f'{mg_age}日前'}）")
        run(py + [str(BASE / "fetch_margin.py")])
    else:
        print(f"\n[3/4] 信用残は{mg_age}日前のものを使います")

    print("\n[4/4] ページを作り直します")
    if run(py + [str(BASE / "build_site.py")]) != 0:
        print("  [NG] ページを作れませんでした。")
        return 1

    if no_push:
        print("\n--no-push のため GitHub には反映しません。")
        return 0

    print("\nGitHub に反映します")
    git("add", "docs")
    if not git("status", "--porcelain", "docs"):
        print("  変化がないので反映しません。")
        return 0
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    git("commit", "-m", f"候補リストを更新 {stamp}", check=True)
    out = subprocess.run(["git", "push"], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(f"  [NG] push に失敗: {(out.stderr or '').strip()[:300]}")
        return 1
    print(f"  反映しました（{stamp}）")
    print(f"\n所要 {dt.datetime.now() - started}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
