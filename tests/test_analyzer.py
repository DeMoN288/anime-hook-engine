from anime_hook.analyzer import HookAnalyzer
from anime_hook.models import EvidenceBundle, LocalizedTitle, Review, TitleProfile

def test_hook_analyzer_instant_hook():
    analyzer = HookAnalyzer()
    profile = TitleProfile(
        id=1,
        title=LocalizedTitle(ru="Тест", en="Test"),
        synopsis="Deadly battle and betrayal in the very first episode.",
        score=8.5,
        genres=["Action", "Fantasy"]
    )
    reviews = [
        Review(text="hooked from the first episode and instant-hook action", source="anilist", id="1"),
        Review(text="захватывает с первой серии, шедевр драмы", source="shikimori", id="2")
    ]
    bundle = EvidenceBundle(profile=profile, reviews=reviews)
    report = analyzer.analyze(bundle)
    assert report.hvi >= 60
    assert report.pacing_type == "INSTANT_HOOK"

def test_hook_analyzer_slow_start():
    analyzer = HookAnalyzer()
    profile = TitleProfile(
        id=2,
        title=LocalizedTitle(ru="Слоу", en="Slow"),
        synopsis="A calm and peaceful village life.",
        score=7.0,
        genres=["Slice of Life"]
    )
    reviews = [
        Review(text="Very slow start, boring beginning until episode 10.", source="anilist", id="1")
    ]
    bundle = EvidenceBundle(profile=profile, reviews=reviews)
    report = analyzer.analyze(bundle)
    assert report.hvi < 60
    assert report.pacing_type in ("SLOW_BURN", "DROP_PRONE")
