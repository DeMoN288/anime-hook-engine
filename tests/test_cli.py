from io import StringIO

from rich.console import Console

from anime_hook.cli import build_parser, render_analysis, render_recommendations
from anime_hook.models import (
    HookReport,
    LocalizedTitle,
    Recommendation,
    RecommendationResult,
    TitleProfile,
)


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["recommend", "Sword Art Online", "--limit", "3", "--json"])
    assert args.command == "recommend"
    assert args.title == "Sword Art Online"
    assert args.limit == 3
    assert args.json is True


def test_cli_render_tables():
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=100)
    profile = TitleProfile(id=1, title=LocalizedTitle(ru="САО", en="SAO"), genres=["Action"])
    report = HookReport(
        hvi=75.0,
        drama_score=55.0,
        pacing_type="INSTANT_HOOK",
        verdict="MUST_WATCH",
        key_cues=["first_episode_hook"],
        confidence=0.5,
        evidence_count=2,
    )
    render_analysis(console, profile, report)
    result = RecommendationResult(
        seed=profile,
        items=[Recommendation(profile=profile, report=report, rank_score=70.0, similarity=0.8)],
        candidates_checked=1,
    )
    render_recommendations(console, result)
    output = buf.getvalue()
    assert "САО" in output
    assert "INSTANT_HOOK" in output
    assert "Проверено кандидатов: 1" in output
