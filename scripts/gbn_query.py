#!/usr/bin/env python3
"""Lightweight CLI for querying pre-indexed GBN parquet data via DuckDB.

Expected parquet schema:
- lang TEXT
- n INTEGER
- ngram_raw TEXT
- ngram_lex TEXT
- pos_pattern TEXT
- year INTEGER
- match_count BIGINT
- volume_count BIGINT
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def build_where(args: argparse.Namespace) -> tuple[str, list[object]]:
    clauses: list[str] = ["lang = ?"]
    params: list[object] = [args.lang]

    if args.n:
        placeholders = ",".join(["?"] * len(args.n))
        clauses.append(f"n IN ({placeholders})")
        params.extend(args.n)

    if args.exact:
        clauses.append("ngram_lex = ?")
        params.append(args.exact)

    if args.prefix:
        clauses.append("ngram_lex LIKE ?")
        params.append(f"{args.prefix}%")

    if args.contains:
        clauses.append("ngram_lex LIKE ?")
        params.append(f"%{args.contains}%")

    if args.regex:
        clauses.append("regexp_matches(ngram_lex, ?)")
        params.append(args.regex)

    if args.pos:
        clauses.append("pos_pattern = ?")
        params.append(args.pos)

    if args.year_from is not None:
        clauses.append("year >= ?")
        params.append(args.year_from)

    if args.year_to is not None:
        clauses.append("year <= ?")
        params.append(args.year_to)

    return " AND ".join(clauses), params


def build_select(metric: str) -> tuple[str, str]:
    if metric == "matches":
        return "SUM(match_count) AS matches", "year\tmatches"
    if metric == "books":
        return "SUM(volume_count) AS books", "year\tbooks"
    return "SUM(match_count) AS matches, SUM(volume_count) AS books", "year\tmatches\tbooks"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query GBN parquet index")
    parser.add_argument("--index-root", required=True, help="Path to indexed parquet root")
    parser.add_argument("--lang", required=True, help="Language partition, e.g. english/russian")
    parser.add_argument("--n", type=int, nargs="*", help="Filter n-gram size(s), e.g. --n 1 2")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exact", help="Exact ngram_lex match")
    group.add_argument("--prefix", help="Prefix search")
    group.add_argument("--contains", help="Substring search")
    group.add_argument("--regex", help="Regex search over ngram_lex")

    parser.add_argument("--pos", help="Exact POS pattern filter")
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--year-to", type=int)
    parser.add_argument(
        "--metric",
        choices=["both", "matches", "books"],
        default="both",
        help="Output metric: token frequency (matches), books (volume_count), or both",
    )
    args = parser.parse_args()

    index_root = Path(args.index_root)
    parquet_glob = str(index_root / f"lang={args.lang}" / "n=*" / "*.parquet")

    where_sql, params = build_where(args)
    select_sql, header = build_select(args.metric)

    sql = f"""
        SELECT
            year,
            {select_sql}
        FROM read_parquet(?)
        WHERE {where_sql}
        GROUP BY year
        ORDER BY year
    """

    con = duckdb.connect()
    rows = con.execute(sql, [parquet_glob, *params]).fetchall()

    print(header)
    for row in rows:
        print("\t".join(str(cell) for cell in row))


if __name__ == "__main__":
    main()
