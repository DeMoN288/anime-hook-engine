# Anime Hook & Drama Intelligence Engine

Async bilingual CLI & engine to analyze anime opening pacing, emotional peaks, Hook Velocity Index (HVI), and generate genre-matched recommendations with fast early hooks (tested on Solo Leveling, SAO, Attack on Titan).

## Features
- **Hook Velocity Index (HVI)**: Heuristic NLP analysis measuring episode 1 hook speed and engagement.
- **DramaScore**: Tracks high-stakes narrative signals (conflicts, survivals, climaxes, betrayals).
- **Multi-Source Evidence**: Shikimori & AniList data with proxy support (`--proxy http://127.0.0.1:2080`).
- **CLI & Rich formatting**: Pretty colored terminal tables and JSON output mode.

## Installation
```bash
git clone https://github.com/DeMoN288/anime-hook-engine.git
cd anime-hook-engine
python -m venv .venv
.\.venv\Scripts\activate
pip install .
```

## Usage
```bash
# Analyze a title
anime-hook analyze "Sword Art Online" --proxy http://127.0.0.1:2080

# Get recommendations for fast-paced titles
anime-hook recommend "Solo Leveling" --proxy http://127.0.0.1:2080 --limit 5
```
