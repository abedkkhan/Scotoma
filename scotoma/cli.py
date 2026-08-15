"""Command-line interface for Scotoma."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table

from .index import build_index


def _print_summary(index: dict, console: Console) -> None:
    overview = Table(title="Scotoma Territory Index", show_header=False)
    overview.add_column("Metric", style="cyan")
    overview.add_column("Value", justify="right", style="bold white")
    overview.add_row("Source units", f"{index['unit_count']:,}")
    overview.add_row("Total LOC", f"{index['total_loc']:,}")
    console.print(overview)

    languages = Counter(unit["language"] for unit in index["units"])
    breakdown = Table(title="Language Breakdown")
    breakdown.add_column("Language", style="cyan")
    breakdown.add_column("Files", justify="right")
    for language, count in sorted(languages.items(), key=lambda item: (-item[1], item[0])):
        breakdown.add_row(language, str(count))
    console.print(breakdown)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scotoma", description="Measure agent investigation blind spots.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    index_parser = subcommands.add_parser("index", help="Index the source territory in a repository.")
    index_parser.add_argument("repo_path", help="Repository directory to index.")
    index_parser.add_argument("--out", default="index.json", help="Output JSON path (default: index.json).")
    ask_parser = subcommands.add_parser("ask", help="Run a traced code-analysis agent.")
    ask_parser.add_argument("repo_path", help="Repository directory to analyze.")
    ask_parser.add_argument("question", help="Question for the code-analysis agent.")
    ask_parser.add_argument("--out", default="trace.json", help="Output trace path (default: trace.json).")
    cover_parser = subcommands.add_parser("cover", help="Calculate risk-weighted investigation coverage.")
    cover_parser.add_argument("--index", required=True, dest="index_path", help="Territory index JSON path.")
    cover_parser.add_argument("--trace", required=True, dest="trace_path", help="Agent trace JSON path.")
    cover_parser.add_argument("--out", default="coverage.json", help="Output coverage path.")
    cover_parser.add_argument("--cache", default="embeddings_cache.json", help="Embedding cache path.")
    adjudicate_parser = subcommands.add_parser("adjudicate", help="Rerank blind spots against extracted claims.")
    adjudicate_parser.add_argument("--index", required=True, dest="index_path")
    adjudicate_parser.add_argument("--trace", required=True, dest="trace_path")
    adjudicate_parser.add_argument("--coverage", required=True, dest="coverage_path")
    adjudicate_parser.add_argument("--out", default="adjudication.json")
    adjudicate_parser.add_argument("--cache", default="adjudication_cache.json")
    flip_parser = subcommands.add_parser("flip", help="Re-answer after preloading top blind spots.")
    flip_parser.add_argument("--adjudication", required=True, dest="adjudication_path")
    flip_parser.add_argument("--out", default="flip.json")
    flip_parser.add_argument("--cache", default="adjudication_cache.json")
    return parser


def _print_trace(trace: dict, console: Console) -> None:
    console.print("\n[bold cyan]Answer[/bold cyan]")
    console.print(trace["answer"])
    console.print(f"\n[bold]Tool calls used:[/bold] {len(trace['tool_calls'])}")
    table = Table(title="Examined Files")
    table.add_column("File", style="cyan")
    table.add_column("Depth", justify="right")
    for path, depth in sorted(trace["examined"].items(), key=lambda item: (-item[1], item[0])):
        table.add_row(path, f"{depth:.2f}")
    console.print(table)


def _print_coverage(coverage: dict, console: Console) -> None:
    console.print(
        f"\n[bold magenta]RISK-WEIGHTED COVERAGE: {coverage['rwc_percent']:.2f}%[/bold magenta]"
    )
    console.print(
        f"Naive file-count coverage: {coverage['examined_unit_count']}/{coverage['unit_count']} "
        f"= {coverage['naive_file_coverage_percent']:.2f}%"
    )
    console.print(
        f"Dependency graph: {coverage['dependency_edges']} edges; "
        f"{coverage['structural_nonzero_units']} units with non-zero structural proximity"
    )
    console.print(f"Embedding API calls this run: {coverage['embedding_api_calls']}")
    table = Table(title="Highest-Risk Blind Spots")
    table.add_column("Path", style="cyan", overflow="fold")
    table.add_column("Rel", justify="right")
    table.add_column("Sem", justify="right")
    table.add_column("Struct", justify="right")
    table.add_column("Lex", justify="right")
    table.add_column("Depth", justify="right")
    table.add_column("Blind risk", justify="right", style="bold red")
    for unit in coverage["units"][:15]:
        table.add_row(
            unit["path"],
            f"{unit['relevance']:.3f}",
            f"{unit['sem']:.3f}",
            f"{unit['struct']:.3f}",
            f"{unit['lex']:.3f}",
            f"{unit['depth']:.2f}",
            f"{unit['blind_risk']:.3f}",
        )
    console.print(table)


def _print_adjudication(result: dict, console: Console) -> None:
    claims = Table(title="Extracted Claims")
    claims.add_column("ID", style="bold cyan")
    claims.add_column("Claim", overflow="fold")
    for claim in result["claims"]:
        claims.add_row(claim["id"], claim["text"])
    console.print(claims)

    table = Table(title="Claim-Adjudicated Blind Spots")
    table.add_column("Path", style="cyan", overflow="fold")
    table.add_column("P(overturn)", justify="right")
    table.add_column("Depth", justify="right")
    table.add_column("Final risk", justify="right", style="bold red")
    table.add_column("Verdict")
    table.add_column("Claim")
    table.add_column("Reason", overflow="fold")
    for item in result["ranked_candidates"]:
        table.add_row(
            item["path"],
            f"{item['overturn_probability']:.2f}",
            f"{item['depth']:.2f}",
            f"{item['adjudicated_risk']:.2f}",
            item["verdict"],
            item["target_claim_id"] or "—",
            item["reason"],
        )
    console.print(table)
    console.print(f"Adjudication API calls this run: {result['adjudication_api_calls']}")


def _print_flip(result: dict, console: Console) -> None:
    console.print(
        Columns(
            [
                Panel(result["old_answer"], title="Original Answer", border_style="red"),
                Panel(result["new_answer"], title="Evidence-Loaded Answer", border_style="green"),
            ],
            equal=True,
            expand=True,
        )
    )
    comparison = result["comparison"]
    changed = "YES" if comparison["changed"] else "NO"
    console.print(f"\n[bold magenta]Conclusion changed: {changed}[/bold magenta]")
    console.print(f"[bold]Summary:[/bold] {comparison['summary']}")
    if comparison["changed_claims"]:
        console.print("[bold]Changed claims:[/bold]")
        for claim in comparison["changed_claims"]:
            console.print(f" • {claim}")
    console.print(f"[bold]Preloaded files:[/bold] {', '.join(result['preloaded_files'])}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    console = Console()
    if args.command == "index":
        try:
            index = build_index(args.repo_path)
            output_path = Path(args.out).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        except (OSError, ValueError) as error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            return 1
        _print_summary(index, console)
        console.print(f"[green]Wrote index to[/green] {output_path.resolve()}")
        return 0
    if args.command == "ask":
        try:
            from .agent import run_agent

            trace = run_agent(args.repo_path, args.question)
            output_path = Path(args.out).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            return 1
        _print_trace(trace, console)
        console.print(f"[green]Wrote trace to[/green] {output_path.resolve()}")
        return 0
    if args.command == "cover":
        try:
            from .rank import calculate_coverage

            index = json.loads(Path(args.index_path).read_text(encoding="utf-8"))
            trace = json.loads(Path(args.trace_path).read_text(encoding="utf-8"))
            coverage = calculate_coverage(index, trace, cache_path=args.cache)
            output_path = Path(args.out).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            return 1
        _print_coverage(coverage, console)
        console.print(f"[green]Wrote coverage to[/green] {output_path.resolve()}")
        return 0
    if args.command == "adjudicate":
        try:
            from .adjudicate import adjudicate

            index = json.loads(Path(args.index_path).read_text(encoding="utf-8"))
            trace = json.loads(Path(args.trace_path).read_text(encoding="utf-8"))
            coverage = json.loads(Path(args.coverage_path).read_text(encoding="utf-8"))
            result = adjudicate(index, trace, coverage, cache_path=args.cache)
            output_path = Path(args.out).expanduser()
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            return 1
        _print_adjudication(result, console)
        console.print(f"[green]Wrote adjudication to[/green] {output_path.resolve()}")
        return 0
    if args.command == "flip":
        try:
            from .adjudicate import run_flip

            adjudication = json.loads(Path(args.adjudication_path).read_text(encoding="utf-8"))
            result = run_flip(adjudication, cache_path=args.cache)
            output_path = Path(args.out).expanduser()
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            return 1
        _print_flip(result, console)
        console.print(f"[green]Wrote flip result to[/green] {output_path.resolve()}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
