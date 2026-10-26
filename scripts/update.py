# -*- coding: utf-8 -*-
"""ページの更新をまとめて行う（必要なときに手動で実行する）。

  1. 財務（1株あたりの値）が古ければ取り直す（週1回・遅い）
  2. 株価を取り直す（全銘柄・約1分）
  3. ページを作り直す（renzoku.html・kitaichi.html と、トップ index.html・共通する銘柄 common.html）。
     トップの「銘柄検索」が読む docs/per/（PER・PER×PBRの履歴・銘柄一覧）と docs/detail/（スクリーニングの全要素）、
     保有銘柄シートが読む docs/summary.csv、日本株ETFシートが読む docs/etf/ もここで作る
  4. GitHub に反映する（変化があったときだけ）

株価だけ取ればよいのは、PER・PBR・時価総額・配当利回りを
「その日の株価 × 1株あたりの値」で出しているため。

2026-09-25 に②（高配当・優待）向けのページへ作り替えた。信用残（JPXの
週末残高PDF）はスイング用の③にしか使っていなかったので取得をやめた。
2026-10-18 に「配当株の買い場」を削除し、トップ（各ページへのリンク）と
「共通する銘柄」（common.html）を追加した。
2026-10-26 に「高配当株 15指標チェック」「グロース株の候補」を削除し、PER×PBR を足した。
共通する銘柄は「連続増配株 × 期待値投資」だけにした。

使い方:
    python scripts/update.py            通常（これを実行する）
    python scripts/update.py --full     財務も必ず取り直す
    python scripts/update.py --no-push  GitHub に反映しない（手元で確認するとき）
"""
import datetime as dt
import glob
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = ROOT / "data"
FUND_MAX_AGE_DAYS = 7      # 1株あたりの値は決算ごとにしか変わらない


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


def add_docs() -> None:
    """docs を git に登録する。ファイルが多いと、ウイルス対策ソフトなどが書き込み中のファイルを
    つかんで失敗することがある（2026-10-18、PER検索の3,600ファイルで発生）ので、
    失敗したら少し待って、小分けにしてやり直す。"""
    for _ in range(3):
        if subprocess.run(["git", "add", "docs"], cwd=str(ROOT), capture_output=True).returncode == 0:
            return
        time.sleep(3)
    files = git("ls-files", "-m", "-o", "--exclude-standard", "docs").splitlines()
    for i in range(0, len(files), 200):
        for _ in range(5):
            if subprocess.run(["git", "add", "--", *files[i:i + 200]], cwd=str(ROOT),
                              capture_output=True).returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError("docs を git に登録できませんでした。少し待ってからもう一度更新してください")
    git("add", "-u", "docs")          # 消えたファイルの分


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
        print(f"\n[1/3] 財務（1株あたりの値）を取り直します（{why}）")
        if run(py + [str(BASE / "fetch_data.py"), "--fundamentals-only"]) == 0:
            # 取得制限で失敗した銘柄を1社ずつ取り直す
            run(py + [str(BASE / "retry_fundamentals.py"), "--pause", "1.0"])
    else:
        print(f"\n[1/3] 財務は{fund_age}日前のものを使います（取り直しません）")

    print("\n[2/3] 株価を取り直します")
    if run(py + [str(BASE / "fetch_data.py"), "--prices-only"]) != 0:
        print("  [NG] 株価が取れませんでした。ページは作り直しません。")
        return 1

    print("\n[3/3] ページを作り直します")
    # 連続増配株・期待値投資。EDINET のAPIキー（.edinet_key）が要る。報告書は保存して使い回す
    if not (ROOT / ".edinet_key").exists():
        print("  [NG] EDINET のAPIキー（.edinet_key）が無いので、ページを作れません")
        return 1
    ok = 0
    for script, name in (("build_renzoku.py", "連続増配株"), ("build_kitaichi.py", "期待値投資")):
        if run(py + [str(BASE / script)]) == 0:
            ok += 1
        else:
            print(f"  [!] {name}のページは作れませんでした（ほかのページは続けて作ります）")
    # トップの「銘柄検索」が読む、銘柄ごとの過去10年のPER・PER×PBR（docs/per/コード.csv）と銘柄一覧
    if run(py + [str(BASE / "build_per_data.py")], timeout=3 * 3600) != 0:
        print("  [!] PERの履歴（銘柄検索用）は作れませんでした（ほかのページは更新済み）")
    elif run(py + [str(BASE / "build_per_page.py")]) != 0:
        print("  [!] 銘柄検索の銘柄一覧は作れませんでした")
    # 検索結果に出すスクリーニングの全要素（全銘柄。決算書は30日ごとに取り直すので、その回は時間がかかる）
    if run(py + [str(BASE / "build_detail.py")], timeout=3 * 3600) != 0:
        print("  [!] 検索結果のスクリーニングの要素は作れませんでした")
    # 保有銘柄のスプレッドシートが読む、全銘柄の検索結果のまとめ（docs/summary.csv）
    elif run(py + [str(BASE / "build_summary.py")]) != 0:
        print("  [!] スプレッドシート用のまとめ（summary.csv）は作れませんでした")
    # 日本株ETFのスプレッドシートが読む、東証の全ETF・ETNの値動きと分配金（docs/etf/）
    if run(py + [str(BASE / "build_etf.py")]) != 0:
        print("  [!] ETFのデータ（スプレッドシート用）は作れませんでした")
    # トップと「共通する銘柄」（上の2ページの結果を読むので最後に作る）
    if run(py + [str(BASE / "build_top.py")]) != 0:
        print("  [!] トップ・共通する銘柄のページは作れませんでした")
    if ok == 0:
        print("  [NG] ページを作れませんでした。")
        return 1

    if no_push:
        print("\n--no-push のため GitHub には反映しません。")
        return 0

    print("\nGitHub に反映します")
    add_docs()
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
