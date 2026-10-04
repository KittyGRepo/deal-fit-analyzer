"""Download filings and build profiles, caching both so re-runs are free."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from .edgar import Filing, download_filing_text, extract_sections
from .profile import DEFAULT_MODEL, PROMPT_VERSION, Profile, build_profile

DEFAULT_CACHE = Path(os.environ.get("DEAL_FIT_CACHE", Path("filings") / "cache"))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def filing_text(
    f: Filing, cache_dir: Path = DEFAULT_CACHE, log: Callable[[str], None] = _log
) -> str:
    path = cache_dir / f"{f.ticker}_{f.accession}.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    log(f"Downloading {f.label} {f.form} (filed {f.filed})...")
    text = download_filing_text(f)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def profile_for(
    f: Filing,
    cache_dir: Path = DEFAULT_CACHE,
    model: str = DEFAULT_MODEL,
    refresh: bool = False,
    api_key: str | None = None,
    log: Callable[[str], None] = _log,
) -> Profile:
    """Build (or load from cache) the acquirer profile for one filing.

    Cached profiles come from public filings, so they are safe to share between
    users. The API key is only used on a cache miss.
    """
    path = cache_dir / f"{f.ticker}_{f.accession}_{PROMPT_VERSION}.json"
    meta = {"form": f.form, "period": f.period, "filed": f.filed, "url": f.url, "label": f.label}
    if path.is_file() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        log(f"{f.label}: using saved profile")
        return Profile(cached["data"], cached["filing"])
    text = filing_text(f, cache_dir, log)
    sections = extract_sections(text) or {"business": text[:200_000]}
    log(f"{f.label}: reading {sum(len(v) for v in sections.values()):,} characters...")
    profile = build_profile(sections, meta, model=model, api_key=api_key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data": profile.data, "filing": meta}), encoding="utf-8")
    return profile
