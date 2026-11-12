from anime_hook.analyzer import HookAnalyzer, extract_votes
from anime_hook.models import EvidenceBundle, LocalizedTitle, Review, TitleProfile


def _bundle(reviews: list[str], *, synopsis: str = "") -> EvidenceBundle:
    profile = TitleProfile(
        id=1,
        title=LocalizedTitle(ru="Тест", en="Test"),
        synopsis=synopsis,
        score=8.5,
        genres=["Action", "Fantasy"],
    )
    return EvidenceBundle(
        profile=profile,
        reviews=[Review(text=text, source="anilist", id=str(i)) for i, text in enumerate(reviews)],
    )


def test_hook_analyzer_instant_hook():
    analyzer = HookAnalyzer()
    report = analyzer.analyze(
        _bundle(
            [
                "hooked from the first episode and instant-hook action, made me cry",
                "захватывает с первой серии, шедевр драмы",
            ],
            synopsis="Deadly battle and betrayal in the very first episode.",
        )
    )
    assert report.hvi >= 65
    assert report.drama_score >= 50
    assert report.pacing_type == "INSTANT_HOOK"
    assert report.verdict == "MUST_WATCH"


def test_hook_analyzer_slow_start():
    analyzer = HookAnalyzer()
    report = analyzer.analyze(
        _bundle(
            ["Very slow start, boring beginning until episode 10."],
            synopsis="A calm and peaceful village life.",
        )
    )
    assert report.hvi < 60
    assert report.pacing_type in ("SLOW_BURN", "DROP_PRONE")
    assert report.verdict == "AVOID_SLOW_START"


def test_hook_analyzer_negation_and_later_episode_filter():
    votes_pos, _ = extract_votes("Тайтл не скучный, без затянутости с первой серии.")
    assert "fast" in votes_pos
    assert "slow" not in votes_pos

    votes_neg, cues_neg = extract_votes("Not a fast-paced start at all.")
    assert "slow" in votes_neg
    assert "negated:fast_pacing" in cues_neg

    votes_late, _ = extract_votes("Action is fast-paced only after episode 10.")
    assert "fast" not in votes_late


def test_hook_analyzer_deduplicates_reviews_and_handles_empty_evidence():
    analyzer = HookAnalyzer()
    single = analyzer.analyze(_bundle(["захватывает с первой серии"]))
    duplicated = analyzer.analyze(
        _bundle(["захватывает с первой серии", "  Захватывает   с первой серии  "])
    )
    assert single.hvi == duplicated.hvi
    assert single.evidence_count == duplicated.evidence_count == 1

    empty = analyzer.analyze(_bundle([]))
    assert empty.hvi == 45.0
    assert empty.pacing_type == "DROP_PRONE"
    assert empty.verdict == "AVOID_SLOW_START"
    assert empty.warnings
