"""
Reddit strategy scraper — pulls top posts about 0DTE and short-squeeze
trading from the most-relevant subreddits, then asks Claude Haiku to
extract recurring patterns: entry setups, exit rules, risk management,
common failure modes.

Output is a structured JSON synthesis used to inform algorithm changes.
This is research, not a permanent feature — run it occasionally, read
the output, propose specific changes.

Honest caveat: Reddit posts are heavily survivorship-biased. Winners
post their wins, losers go silent. The synthesis surfaces patterns
people TALK about, not necessarily patterns that statistically work.
The value is identifying gaps in what we already model, not validating
strategies as profitable.

Free, no-auth, uses Reddit's public JSON endpoints. Rate-limited to
~60 requests/min by Reddit; we batch responsibly.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.analyst.openrouter import MODELS, OpenRouterError, _extract_json
from src.analyst.openrouter import URL as OPENROUTER_URL
from src.config import OPENROUTER_API_KEY

USER_AGENT = "squeeze-finder-research/0.1 (educational use)"

# (subreddit, query, why we picked it)
SOURCES: list[tuple[str, str, str]] = [
    ("options",        "0dte",    "0DTE trader wisdom from a sophisticated options community"),
    ("options",        "scalp",   "intraday scalping tactics adjacent to 0DTE"),
    ("thetagang",      "0dte",    "premium-seller perspective on 0DTE — counterpoint to long-only"),
    ("Daytrading",     "0dte",    "broader intraday techniques (VWAP, ORB, levels)"),
    ("wallstreetbets", "0dte",    "retail tactics + recent winners/losers"),
    ("wallstreetbets", "squeeze", "squeeze-hunting tactics from the source community"),
    ("Vitards",        "squeeze", "squeeze-focused due diligence (commodity-tilted)"),
    ("Superstonk",     "squeeze", "deep squeeze theorycrafting (GME-centric, take with salt)"),
    ("SqueezePlays",   "",        "dedicated squeeze-screening community"),
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _reddit_get(url: str) -> dict | None:
    """GET against Reddit's public JSON. 429 is non-retryable here (we'd just keep getting blocked)."""
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if r.status_code == 429:
        return None
    r.raise_for_status()
    return r.json()


def scrape_subreddit(subreddit: str, query: str, limit: int = 30, time_filter: str = "year") -> list[dict]:
    """Top posts in `subreddit` matching `query` (or top overall if query empty)."""
    if query:
        url = (
            f"https://www.reddit.com/r/{subreddit}/search.json"
            f"?q={query}&restrict_sr=1&sort=top&t={time_filter}&limit={limit}"
        )
    else:
        url = f"https://www.reddit.com/r/{subreddit}/top.json?t={time_filter}&limit={limit}"

    data = _reddit_get(url)
    if not data:
        return []

    out: list[dict] = []
    for child in data.get("data", {}).get("children", []) or []:
        d = child.get("data") or {}
        if d.get("stickied") or d.get("removed_by_category"):
            continue
        title = (d.get("title") or "").strip()
        body = (d.get("selftext") or "").strip()
        if not title:
            continue
        # Skip pure link posts with no content unless title is very informative
        if not body and len(title) < 30:
            continue
        out.append({
            "subreddit": subreddit,
            "title": title,
            "selftext": body[:1500],  # truncate long posts
            "score": int(d.get("score") or 0),
            "num_comments": int(d.get("num_comments") or 0),
            "permalink": f"https://reddit.com{d.get('permalink', '')}",
            "id": d.get("id"),
            "created_utc": d.get("created_utc"),
            "flair": d.get("link_flair_text"),
        })
    return out


def fetch_top_comments(post_permalink: str, limit: int = 5) -> list[dict]:
    """Top comments on a post by upvotes. Returns trimmed comment text + score."""
    url = post_permalink.rstrip("/") + ".json?limit=20"
    data = _reddit_get(url)
    if not data or len(data) < 2:
        return []
    children = data[1].get("data", {}).get("children", []) or []
    comments = []
    for c in children:
        cd = c.get("data") or {}
        body = (cd.get("body") or "").strip()
        if not body or body in ("[deleted]", "[removed]"):
            continue
        comments.append({"body": body[:600], "score": int(cd.get("score") or 0)})
        if len(comments) >= limit:
            break
    return sorted(comments, key=lambda c: c["score"], reverse=True)


def harvest(per_source_limit: int = 25, with_comments: bool = True) -> dict[str, Any]:
    """Pull the full corpus across all (subreddit, query) sources."""
    posts: list[dict] = []
    for sub, q, why in SOURCES:
        try:
            batch = scrape_subreddit(sub, q, limit=per_source_limit)
        except Exception as e:
            batch = []
            print(f"  WARN: r/{sub} query={q!r} failed: {e}")
        for p in batch:
            p["source_reason"] = why
        posts.extend(batch)
        time.sleep(1.2)  # rate-limit politely

    # Dedupe by post id (a post can match multiple queries)
    seen_ids: set[str] = set()
    unique: list[dict] = []
    for p in posts:
        pid = p.get("id")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        unique.append(p)

    # Top-by-score across the union, take the most upvoted to give Haiku a
    # high-signal corpus
    unique.sort(key=lambda p: p["score"], reverse=True)
    top = unique[:60]

    if with_comments:
        for p in top[:30]:  # comments only on top 30 to bound work
            try:
                p["top_comments"] = fetch_top_comments(p["permalink"], limit=3)
            except Exception:
                p["top_comments"] = []
            time.sleep(0.6)

    return {
        "as_of": datetime.now(UTC).isoformat(),
        "n_sources": len(SOURCES),
        "n_unique_posts": len(unique),
        "n_in_corpus": len(top),
        "posts": top,
    }


SYNTHESIS_PROMPT = (
    "You are a quantitative trading research analyst. Below is a corpus of "
    "high-upvoted Reddit posts from options/squeeze trading subreddits. Your "
    "job: extract RECURRING, ACTIONABLE patterns — not anecdotes. Output strict JSON "
    "matching this schema:\n\n"
    "{\n"
    '  "zero_dte": {\n'
    '    "entry_setups": [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "exit_rules":   [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "risk_mgmt":    [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "common_failures": ["...", "..."]\n'
    '  },\n'
    '  "squeezes": {\n'
    '    "screening_criteria": [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "entry_triggers":     [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "exit_rules":         [{"name": "...", "what": "...", "evidence_count": N}],\n'
    '    "common_failures":    ["...", "..."]\n'
    '  },\n'
    '  "data_sources_mentioned": ["..."],\n'
    '  "tools_mentioned": ["..."],\n'
    '  "honest_caveats": "1-2 sentences on survivorship bias / what to be skeptical of"\n'
    "}\n\n"
    "Rules:\n"
    "- evidence_count = number of posts/comments mentioning this pattern (estimate from corpus)\n"
    "- ONLY include patterns mentioned in 3+ posts/comments — kill one-offs\n"
    "- 'what' should be specific and operationalizable (a rule a backtest could implement)\n"
    "- 'common_failures' = recurring losing-trade patterns mentioned by users\n"
    "- Be skeptical: many posts are survivorship-biased winners; favor patterns echoed by losing-trade post-mortems\n"
    "- Return ONLY the JSON object, no prose, no markdown."
)


def synthesize_with_haiku(harvest_data: dict, timeout: float = 90) -> dict:
    """Send the corpus to Claude Haiku and parse its structured synthesis."""
    if not OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY not set")

    # Slim the corpus for token budget — Haiku context is plenty but no need
    # to send raw scores or permalinks
    slim_posts = []
    for p in harvest_data["posts"]:
        slim_posts.append({
            "sr": p["subreddit"],
            "title": p["title"],
            "text": p.get("selftext", "")[:800],
            "score": p["score"],
            "n_comments": p["num_comments"],
            "top_comments": [c["body"][:400] for c in (p.get("top_comments") or [])[:3]],
        })

    facts = {
        "n_posts": len(slim_posts),
        "subreddits_covered": sorted({p["sr"] for p in slim_posts}),
        "posts": slim_posts,
    }

    last_error = None
    for model in MODELS:
        try:
            r = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "squeeze-finder/research-reddit",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYNTHESIS_PROMPT},
                        {"role": "user", "content": json.dumps(facts, default=str, indent=2)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 3000,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if isinstance(parsed, dict):
                return {**parsed, "model_used": model}
            last_error = f"{model}: invalid response shape"
        except Exception as e:
            last_error = f"{model}: {e}"

    raise OpenRouterError(f"reddit synthesis failed; last: {last_error}")


def run(per_source_limit: int = 25, with_comments: bool = True) -> dict[str, Any]:
    """Full research pipeline: harvest -> synthesize. Returns merged result."""
    print(f"Harvesting from {len(SOURCES)} (subreddit, query) sources…")
    harvest_data = harvest(per_source_limit=per_source_limit, with_comments=with_comments)
    print(f"  collected {harvest_data['n_unique_posts']} unique posts; sending top {harvest_data['n_in_corpus']} to Haiku…")
    synthesis = synthesize_with_haiku(harvest_data)
    return {
        "as_of": harvest_data["as_of"],
        "harvest": {
            "n_sources": harvest_data["n_sources"],
            "n_unique_posts": harvest_data["n_unique_posts"],
            "n_in_corpus": harvest_data["n_in_corpus"],
        },
        "synthesis": synthesis,
        "raw_corpus": harvest_data["posts"],  # keep so the user can spot-check
    }
