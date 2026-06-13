#!/usr/bin/env python3
"""ユニバースCSVを生成するヘルパー。

日経公式やJPXなどからダウンロードした構成銘柄CSVを、本アプリの
フォーマット（code,name）に変換する。Webスクレイピングはせず、手元の
CSVを変換するだけなので壊れにくい。

使い方:
    # 入力CSVから銘柄コード列(と任意の名称列)を抽出して出力
    python tools/build_universe.py 入力.csv -o data/universe/nikkei225.csv \
        --code-col コード --name-col 銘柄名

列名を省略した場合は、よくある候補（code/コード/銘柄コード, name/銘柄名/銘柄）を
自動推定する。
"""

from __future__ import annotations

import argparse
import csv
import sys

_CODE_CANDIDATES = ["code", "コード", "銘柄コード", "証券コード", "symbol"]
_NAME_CANDIDATES = ["name", "銘柄名", "銘柄", "名称", "会社名"]


def _pick(header: list[str], explicit: str | None, candidates: list[str]) -> str | None:
    if explicit:
        return explicit
    lower = {h.lower().strip(): h for h in header}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ユニバースCSVを生成")
    ap.add_argument("input", help="入力CSV（公式の構成銘柄一覧など）")
    ap.add_argument("-o", "--output", default="data/universe/nikkei225.csv")
    ap.add_argument("--code-col", help="銘柄コードの列名")
    ap.add_argument("--name-col", help="銘柄名の列名")
    ap.add_argument("--encoding", default="utf-8-sig", help="入力CSVの文字コード")
    args = ap.parse_args(argv)

    with open(args.input, "r", encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("入力CSVにヘッダがありません。", file=sys.stderr)
            return 1
        code_col = _pick(reader.fieldnames, args.code_col, _CODE_CANDIDATES)
        name_col = _pick(reader.fieldnames, args.name_col, _NAME_CANDIDATES)
        if not code_col:
            print(
                f"コード列を特定できません。--code-col で指定してください。"
                f" 利用可能な列: {reader.fieldnames}",
                file=sys.stderr,
            )
            return 1

        rows = []
        seen = set()
        for row in reader:
            code = str(row.get(code_col, "")).strip()
            # 数字4-5桁のコードだけ採用
            digits = "".join(ch for ch in code if ch.isdigit())
            if not digits or digits in seen:
                continue
            seen.add(digits)
            name = str(row.get(name_col, "")).strip() if name_col else ""
            rows.append((digits, name))

    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name"])
        writer.writerows(rows)

    print(f"出力しました: {args.output}（{len(rows)}銘柄）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
