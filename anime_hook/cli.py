"""Command line entry point with Rich output and explicit JSON mode."""

import argparse
import asyncio
import sys

from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import HookReport, RecommendationResult, TitleProfile
from .network import APIError, AsyncAPIClient
from .recommender import Recommender


def _warnings(console: Console, warnings: list[str]) -> None:
    for warning in dict.fromkeys(warnings):
        console.print(Text(f"Предупреждение: {warning}", style="yellow"))


def render_analysis(console: Console, profile: TitleProfile, report: HookReport) -> None:
    table = Table("Показатель", "Значение")
    for label, value in (
        ("HVI", f"{report.hvi:.2f}/100"),
        ("Драма", f"{report.drama_score:.2f}/100"),
        ("Темп", report.pacing_type), ("Вердикт", report.verdict),
        ("Уверенность", f"{report.confidence:.0%}"),
        ("Свидетельства", str(report.evidence_count)),
        ("Сигналы", ", ".join(report.key_cues) or "—"),
    ):
        table.add_row(Text(label), Text(value))
    console.print(Panel(table, title=Text(profile.title.display)))
    for snippet in report.review_snippets:
        console.print(Text(f"  Отзыв: {snippet}", style="cyan"))
    _warnings(console, report.warnings)


def render_recommendations(console: Console, result: RecommendationResult) -> None:
    console.print(Text(f"Рекомендации для: {result.seed.title.display}"))
    table = Table("#", "Тайтл", "ID", "Ранг", "HVI", "Драма", "Сходство", "Темп")
    for index, item in enumerate(result.items, 1):
        table.add_row(
            str(index), Text(item.profile.title.display),
            f"{item.profile.id_source}:{item.profile.id}", f"{item.rank_score:.2f}",
            f"{item.report.hvi:.2f}", f"{item.report.drama_score:.2f}",
            f"{item.similarity:.0%}", item.report.pacing_type,
        )
    console.print(table)
    console.print(f"Проверено кандидатов: {result.candidates_checked}")
    for item in result.items:
        if item.report.review_snippets:
            console.print(Text(f"\n[{item.profile.title.display}]", style="bold"))
            for snippet in item.report.review_snippets:
                console.print(Text(f"  • {snippet}", style="cyan"))
    _warnings(console, result.warnings)
    for item in result.items:
        _warnings(console, [
            f"{item.profile.title.display}: {warning}" for warning in item.report.warnings
        ])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anime-hook", description="Анализ темпа аниме")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (
        ("analyze", "Проанализировать тайтл"),
        ("recommend", "Найти похожие тайтлы с быстрым началом"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("title", help="Название или MAL/Shikimori ID")
        command.add_argument("--proxy", help="URL HTTP/SOCKS-прокси")
        command.add_argument("--no-fallback-proxy", action="store_true")
        command.add_argument("--reviews", type=int, default=20, help="Отзывы на источник (1..50)")
        command.add_argument("--json", action="store_true", help="Вывести JSON вместо таблицы")
        if name == "analyze":
            command.add_argument("--first-episode-summary", default="")
        else:
            command.add_argument("--limit", type=int, default=5)
            command.add_argument("--candidates", type=int, default=10)
            command.add_argument("--min-hvi", type=float, default=60)
            command.add_argument("--min-score", type=float, default=0)
            command.add_argument("--min-similarity", type=float, default=0)
    return parser


async def _run(args: argparse.Namespace, console: Console) -> None:
    if not args.title.strip() or not 1 <= args.reviews <= 50:
        raise ValueError("Укажите тайтл и число отзывов от 1 до 50")
    if args.command == "recommend":
        if not 1 <= args.limit <= args.candidates <= 50:
            raise ValueError("Требуется 1 <= limit <= candidates <= 50")
        if not (0 <= args.min_hvi <= 100 and 0 <= args.min_score <= 10
                and 0 <= args.min_similarity <= 1):
            raise ValueError("Допустимые диапазоны: HVI 0..100, score 0..10, similarity 0..1")
    async with AsyncAPIClient(
        proxy=args.proxy,
        fallback_proxy=None if args.no_fallback_proxy else "socks5://127.0.0.1:2080",
    ) as client:
        recommender = Recommender(client)
        if args.command == "analyze":
            profile = await recommender.resolve(args.title)
            profile.first_episode_summary = args.first_episode_summary
            bundle = await recommender.collect_evidence(profile, review_limit=args.reviews)
            bundle.warnings.extend(recommender.warnings)
            report = recommender.analyzer.analyze(bundle)
            if args.json:
                console.print_json(data={
                    "profile": bundle.profile.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                })
            else:
                render_analysis(console, bundle.profile, report)
        else:
            result = await recommender.recommend(
                args.title, limit=args.limit, candidate_limit=args.candidates,
                min_hvi=args.min_hvi, min_score=args.min_score,
                min_similarity=args.min_similarity, review_limit=args.reviews,
            )
            if args.json:
                console.print_json(data=result.model_dump(mode="json"))
            else:
                render_recommendations(console, result)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    console = Console(highlight=False)
    try:
        asyncio.run(_run(args, console))
    except (APIError, ValidationError, ValueError, KeyError, TypeError) as exc:
        Console(stderr=True).print(Text(f"Ошибка: {exc}", style="red"))
        sys.exit(1)
    except KeyboardInterrupt:
        Console(stderr=True).print("Отменено.")
        sys.exit(130)
