"""Validated domain objects; all indices use the 0..100 scale."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class LocalizedTitle(Model):
    ru: str | None = None
    en: str | None = None
    romaji: str | None = None

    @property
    def display(self) -> str:
        return self.ru or self.en or self.romaji or "Unknown title"


class TitleProfile(Model):
    # MAL and Shikimori share anime identifiers; AniList has a separate namespace.
    id: int = Field(gt=0)
    id_source: Literal["mal", "anilist"] = "mal"
    anilist_id: int | None = Field(default=None, gt=0)
    title: LocalizedTitle
    score: float | None = Field(default=None, ge=0, le=10)
    episodes: int | None = Field(default=None, ge=0)
    genres: list[str] = Field(default_factory=list)
    synopsis: str = ""
    first_episode_summary: str = ""

    @property
    def mal_id(self) -> int | None:
        return self.id if self.id_source == "mal" else None


class Review(Model):
    text: str
    source: Literal["shikimori", "anilist"]
    id: str
    url: str | None = None


class EvidenceBundle(Model):
    profile: TitleProfile
    reviews: list[Review] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HookReport(Model):
    hvi: float = Field(ge=0, le=100)
    drama_score: float = Field(ge=0, le=100)
    pacing_type: Literal["INSTANT_HOOK", "STEADY_FAST", "SLOW_BURN", "DROP_PRONE"]
    verdict: Literal["MUST_WATCH", "GOOD_PACE", "AVOID_SLOW_START"]
    key_cues: list[str] = Field(default_factory=list)
    review_snippets: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)
    components: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_verdict(self) -> "HookReport":
        blocked = self.hvi < 60 or self.pacing_type in {"SLOW_BURN", "DROP_PRONE"}
        if blocked != (self.verdict == "AVOID_SLOW_START"):
            raise ValueError("verdict must respect the hard pacing filter")
        return self


class Recommendation(Model):
    profile: TitleProfile
    report: HookReport
    rank_score: float = Field(ge=0, le=100)
    similarity: float = Field(ge=0, le=1)


class RecommendationResult(Model):
    seed: TitleProfile
    items: list[Recommendation] = Field(default_factory=list)
    candidates_checked: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
