#!/usr/bin/env python3
"""Build a parquet index from Google Books Ngram raw files.

Input line format (GBN):
    ngram<TAB>year,match_count,volume_count<TAB>year,match_count,volume_count...

Output parquet schema (long format):
    lang TEXT
    n INTEGER
    ngram_raw TEXT
    ngram_lex TEXT
    pos_pattern TEXT
    year INTEGER
    match_count BIGINT
    volume_count BIGINT
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import re
from pathlib import Path
from typing import Iterable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

POS_RE = re.compile(r"^(?P<lemma>.+?)_(?P<pos>[A-Z.]+)$")


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def iter_input_files(source_root: Path, n: int) -> Iterator[Path]:
    n_dir = source_root / f"{n}grams"
    if not n_dir.exists():
        return

    for pattern in ("*.gz", "*.bz2", "*.txt", "*.csv"):
        for path in sorted(n_dir.glob(pattern)):
            if path.is_file():
                yield path


def parse_ngram(tokenized_ngram: str, lowercase: bool) -> tuple[str, str]:
    lemmas: list[str] = []
    pos_tags: list[str] = []

    for token in tokenized_ngram.split(" "):
        match = POS_RE.match(token)
        if match:
            lemma = match.group("lemma")
            pos_tags.append(match.group("pos"))
        else:
            lemma = token
            pos_tags.append("")
        lemmas.append(lemma.lower() if lowercase else lemma)

    ngram_lex = " ".join(lemmas)
    pos_pattern = " ".join(tag if tag else "_" for tag in pos_tags)
    return ngram_lex, pos_pattern


def parse_line(line: str, lang: str, n: int, lowercase: bool) -> Iterable[tuple[str, int, str, str, str, int, int, int]]:
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 2:
        return []

    ngram_raw = parts[0]
    ngram_lex, pos_pattern = parse_ngram(ngram_raw, lowercase=lowercase)

    rows = []
    for metrics in parts[1:]:
        triplet = metrics.split(",")
        if len(triplet) != 3:
            continue
        year_str, match_str, volume_str = triplet
        try:
            year = int(year_str)
            match_count = int(match_str)
            volume_count = int(volume_str)
        except ValueError:
            continue

        rows.append((lang, n, ngram_raw, ngram_lex, pos_pattern, year, match_count, volume_count))

    return rows


def write_batch(rows: list[tuple[str, int, str, str, str, int, int, int]], out_file: Path) -> None:
    table = pa.table(
        {
            "lang": [r[0] for r in rows],
            "n": [r[1] for r in rows],
            "ngram_raw": [r[2] for r in rows],
            "ngram_lex": [r[3] for r in rows],
            "pos_pattern": [r[4] for r in rows],
            "year": [r[5] for r in rows],
            "match_count": [r[6] for r in rows],
            "volume_count": [r[7] for r in rows],
        }
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_file, compression="zstd")


def build_index(
    source_root: Path,
    output_root: Path,
    lang: str,
    n_values: list[int],
    batch_rows: int,
    lowercase: bool,
) -> None:
    total_rows = 0

    for n in n_values:
        out_dir = output_root / f"lang={lang}" / f"n={n}"
        part = 0
        buffer: list[tuple[str, int, str, str, str, int, int, int]] = []

        files = list(iter_input_files(source_root, n))
        if not files:
            print(f"[WARN] no files found for {source_root / f'{n}grams'}")
            continue

        print(f"[INFO] n={n}: {len(files)} file(s)")
        for file_path in files:
            print(f"[INFO] reading {file_path}")
            with open_text(file_path) as fh:
                for line in fh:
                    rows = parse_line(line, lang=lang, n=n, lowercase=lowercase)
                    if not rows:
                        continue
                    buffer.extend(rows)

                    if len(buffer) >= batch_rows:
                        part += 1
                        out_file = out_dir / f"part-{part:06d}.parquet"
                        write_batch(buffer, out_file)
                        total_rows += len(buffer)
                        print(f"[INFO] wrote {len(buffer)} rows -> {out_file}")
                        buffer.clear()

        if buffer:
            part += 1
            out_file = out_dir / f"part-{part:06d}.parquet"
            write_batch(buffer, out_file)
            total_rows += len(buffer)
            print(f"[INFO] wrote {len(buffer)} rows -> {out_file}")
            buffer.clear()

    print(f"[DONE] total rows written: {total_rows}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert GBN raw files into parquet index")
    parser.add_argument("--source-root", required=True, help="Path like GBN_2020_English")
    parser.add_argument("--output-root", required=True, help="Path for parquet index root")
    parser.add_argument("--lang", required=True, help="Language name (partition value)")
    parser.add_argument("--n", nargs="+", type=int, default=[1, 2, 3, 4, 5], help="N-gram sizes to parse")
    parser.add_argument("--batch-rows", type=int, default=2_000_000, help="Rows per parquet part")
    parser.add_argument("--lowercase", action="store_true", help="Lowercase ngram_lex")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_index(
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        lang=args.lang,
        n_values=args.n,
        batch_rows=args.batch_rows,
        lowercase=args.lowercase,
    )


if __name__ == "__main__":
    main()
