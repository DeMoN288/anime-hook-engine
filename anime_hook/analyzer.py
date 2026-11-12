"""Deterministic RU/EN heuristics, not a trained psychological predictor.

One document contributes at most one vote per cue category. Pacing statements
explicitly about later episodes are ignored. Drama may refer to the whole show.
"""

import re
from dataclasses import dataclass

from .models import EvidenceBundle, HookReport


@dataclass(frozen=True)
class Cue:
    name: str
    category: str
    pattern: str


CUES = [
    Cue("first_episode_hook", "instant",
        r"захватыва\w*\s+с\s+перв\w*\s+(?:сери\w*|минут\w*)|"
        r"затянул\w*\s+с\s+перв\w*\s+(?:минут\w*|сери\w*)|"
        r"сразу\s+(?:же\s+)?(?:в\s+)?(?:экшен|экшн|действие)|"
        r"(?:hooked|gripping|captivating)\s+(?:me\s+)?(?:from|in)\s+"
        r"(?:the\s+)?(?:very\s+)?first\s+(?:episode|minute)|"
        r"(?:great|strong|amazing|incredible)\s+(?:first\s+episode|opening|start)|"
        r"instant[ -]hook"),
    Cue("binge_worthy", "fast",
        r"binge[ -]worthy|binge[ -]watch\w*|смотр\w*\s+на\s+одном\s+дыхании|не\s+оторваться"),
    Cue("fast_pacing", "fast",
        r"быстр\w*\s+(?:темп|старт)|бодр\w*\s+(?:начал\w*|старт)|динамичн\w*|"
        r"держит\s+в\s+напряжении|fast[ -]paced|fast\s+start|great\s+pacing|"
        r"good\s+pacing|action[- ]packed|never\s+(?:a\s+)?dull\s+moment|"
        r"не\s+скучн\w*|без\s+затянутости"),
    Cue("slow_start", "slow",
        r"долго\s+раскачива\w*|медленн\w*\s+(?:разгон|старт)|"
        r"перв\w*\s+(?:\d+|пять|три|десять)\s+сери\w*\s+(?:\w+\s+)?"
        r"(?:скук\w*|скучн\w*)|slow[ -]start|boring\s+beginning|"
        r"slow[ -]burn|starts?\s+(?:very\s+)?slow(?:ly)?"),
    Cue("late_payoff", "slow",
        r"(?:действие|экшен|экшн|интересн\w*)\s+(?:начина\w*\s+)?"
        r"(?:только|лишь)\s+(?:к|с|на|после)\s+\d+\s*(?:-?й\s+)?сери\w*|"
        r"gets?\s+good\s+(?:only\s+)?(?:after|at)\s+episode\s+\d+"),
    Cue("political_drag", "slow",
        r"затянут\w*\s+политик\w*|нудн\w*\s+разгон|boring\s+politic\w*"),
    Cue("tears", "drama",
        r"рыда\w*|плака\w*|сл[её]зы\s+в\s+конце|стекло|"
        r"cried|crying|(?:made|makes)\s+me\s+cry|in\s+tears"),
    Cue("sacrifice", "drama", r"самопожертвован\w*|self[ -]sacrifice|sacrific\w*"),
    Cue("emotional_peak", "drama",
        r"шедевр\s+драмы|эмоциональн\w*\s+(?:пик|взрыв)|"
        r"emotional\s+peak|heartbreak\w*|heart[ -]breaking"),
    Cue("loyalty_loss", "drama",
        r"потер\w*\s+друга|смерть\s+друга|верность|loyalty|loss\s+of\s+(?:a\s+)?friend"),
]
COMPILED = [(cue, re.compile(r"(?<!\w)(?:" + cue.pattern + r")(?!\w)", re.I))
            for cue in CUES]
SENTENCE = re.compile(r"[.!?;\n]+")
CLAUSE = re.compile(r"[,;:]|\b(?:но|однако|but|however)\b", re.I)
LATER = re.compile(
    r"(?:после|к|с|на)\s+(\d+)\s*(?:-?й\s+)?сери\w*|"
    r"(?:after|at|from|in)\s+(?:episode\s+)?(\d+)(?:\s+episodes?)?", re.I
)
EARLY = re.compile(
    r"перв\w*\s+(?:сери\w*|минут\w*|[123]\s+сери\w*)|"
    r"first\s+(?:episode|minutes?|[123]\s+episodes?)|начал\w*|beginning|start", re.I
)


def _negated(clause: str, start: int, matched: str) -> bool:
    # Explicit double-negative positives must not be negated by their own 'не/без'.
    if re.match(r"не\s+скучн|без\s+затянутости", matched):
        return False
    tokens = re.findall(r"[\w']+", clause[:start].lower())[-3:]
    prefix = " ".join(tokens)
    if re.search(r"(?:не\s+только|not\s+only)$", prefix):
        return False
    return any(token in {"не", "ни", "нет", "без", "not", "no", "never", "isn't",
                         "wasn't", "didn't", "without"} for token in tokens)


def extract_votes(text: str) -> tuple[set[str], list[str]]:
    categories: set[str] = set()
    found: list[str] = []
    for sentence in SENTENCE.split(text.lower().replace("ё", "е")):
        later = any(int(next(g for g in match.groups() if g is not None)) > 3
                    for match in LATER.finditer(sentence))
        for clause in CLAUSE.split(sentence):
            for cue, pattern in COMPILED:
                for match in pattern.finditer(clause):
                    # 'Only gets good after ep 10' is precisely a slow-start cue.
                    if cue.category in {"instant", "fast"} and later and not EARLY.search(clause):
                        continue
                    negated = _negated(clause, match.start(), match.group())
                    category = cue.category
                    if negated:
                        if category == "slow":
                            category = "fast"
                        elif category in {"instant", "fast"}:
                            category = "slow"
                        else:
                            found.append(f"negated:{cue.name}")
                            continue
                    categories.add(category)
                    found.append(("negated:" if negated else "") + cue.name)
    return categories, list(dict.fromkeys(found))


def _review_snippet(text: str, limit: int = 180) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


class HookAnalyzer:
    def analyze(self, bundle: EvidenceBundle) -> HookReport:
        documents: list[tuple[str, float, bool]] = [(r.text, 1.0, True) for r in bundle.reviews]
        if bundle.profile.first_episode_summary:
            documents.append((bundle.profile.first_episode_summary, 0.5, False))
        if bundle.profile.synopsis:
            documents.append((bundle.profile.synopsis, 0.25, False))
        # Equal copied reviews must not multiply evidence, even across APIs.
        seen: set[str] = set()
        numerator, mass = 45.0, 0.0
        drama_numerator, drama_mass = 10.0, 0.0
        counts = {"instant": 0.0, "fast": 0.0, "slow": 0.0}
        cues: list[str] = []
        matched_snippets: list[str] = []
        fallback_snippets: list[str] = []
        evidence_count = 0
        for text, weight, is_review in documents:
            normalized = " ".join(text.casefold().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            votes, document_cues = extract_votes(text)
            cues.extend(document_cues)
            if is_review:
                snippet = _review_snippet(text)
                if votes and len(matched_snippets) < 3:
                    matched_snippets.append(snippet)
                elif len(fallback_snippets) < 3:
                    fallback_snippets.append(snippet)
            if votes:
                evidence_count += 1
            pacing_votes = votes & counts.keys()
            if pacing_votes:
                # A category cannot be amplified by repeating keywords in a review.
                vote = max(0, min(100, 45 + 45 * ("instant" in votes)
                                  + 25 * ("fast" in votes) - 65 * ("slow" in votes)))
                numerator += weight * vote
                mass += weight
                for category in pacing_votes:
                    counts[category] += weight
            # No tears mentioned is NOT proof of no drama, but a conservative prior.
            drama_numerator += weight * (95 if "drama" in votes else 10)
            drama_mass += weight
        hvi = round(numerator / (1 + mass), 2)
        drama = round(drama_numerator / (1 + drama_mass), 2)
        if counts["slow"] > 0 and counts["slow"] >= counts["instant"] + counts["fast"]:
            pacing = "SLOW_BURN"
        elif hvi < 60:
            pacing = "DROP_PRONE"
        elif counts["instant"] > counts["slow"]:
            pacing = "INSTANT_HOOK"
        else:
            pacing = "STEADY_FAST"
        if pacing in {"SLOW_BURN", "DROP_PRONE"} or hvi < 60:
            verdict = "AVOID_SLOW_START"
        elif hvi >= 65 and drama >= 50:
            verdict = "MUST_WATCH"
        else:
            verdict = "GOOD_PACE"
        warnings = list(bundle.warnings)
        if mass == 0:
            warnings.append(
                "Нет свидетельств темпа первых эпизодов; HVI — консервативный prior 45."
            )
        if counts["slow"] and (counts["instant"] or counts["fast"]):
            warnings.append("Отзывы о темпе противоречат друг другу.")
        snippets = (matched_snippets + fallback_snippets)[:3]
        return HookReport(
            hvi=hvi, drama_score=drama, pacing_type=pacing, verdict=verdict,
            key_cues=list(dict.fromkeys(cues)), review_snippets=snippets,
            evidence_count=evidence_count,
            confidence=round(mass / (mass + 3), 3),
            components={"pacing_evidence_weight": mass, **counts}, warnings=warnings,
        )
