"""Compare several years of acquirer profiles: what changed, and said vs. did."""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from .profile import (
    DEFAULT_MODEL,
    QUOTED_FIELDS,
    Profile,
    _arr,
    _normalize_text,
    _obj,
    clean_text,
)

SYSTEM_PROMPT = """\
You are a corporate-strategy research assistant. You receive structured profiles \
of ONE company built from its annual reports (10-Ks) for several consecutive \
years, oldest first. Each item carries a verbatim quote from that year's filing.

Do two analyses:

1. changes: what moved in the company's stated strategy between years. Use \
change = "new" (appears in a later year only), "dropped" (stops appearing), \
"strengthened" or "softened" (same theme, firmer or weaker language or targets), \
or "shifted" (the emphasis moved). Give each change ONE year: the single \
fiscal-year label, exactly as it appears in the profiles (for example "FY2024"), \
in which the change first becomes visible. Never give a range.

2. said_vs_did: for each important stated priority, check whether LATER or \
same-year filings describe real deals, divestitures, partnerships or investments \
that back it up. Verdicts: "backed_by_action" (clear matching action), \
"partly_backed", "no_visible_action" (no matching action appears in ANY year's \
acquisition_history, capability_investments or constraints; this does NOT prove \
none happened, so use it only after checking every year and give low confidence), \
"contradicted" (the actions run against the stated priority). acquisition_history \
holds deals AND other actions such as portfolio reductions, with figures; count \
those as action. Prefer priorities from earlier years, because they have had \
time to play out.

Judge only what the stated priority actually claims. If a priority names a goal \
(a target or a result) and a means (an action), "backed_by_action" needs evidence \
that the GOAL was met or is clearly on track; evidence of the means alone is \
"partly_backed". Split a compound priority into the part the filings evidence and \
the part they do not, and say so in what_filings_show. Use confidence "high" only \
when the filings give direct, specific evidence.

Rules:
- Use ONLY the profiles provided. Never use outside knowledge, never name new \
potential acquisition targets. You may name companies the profiles name.
- evidence_quote must be copied word for word from a quote in the profile of the \
year you give in evidence_year. Copy it exactly and in full, as one unbroken \
passage; never shorten it, skip words, or splice pieces together. If you cannot \
copy an exact passage, use "". Never paraphrase inside a quote.
- Describe patterns, not causes. These are hypotheses for discussion, not \
predictions or advice. Do not recommend buying any company.
- Write for a busy senior executive: every text field is ONE sentence of at most \
30 words. Limits: changes at most 6; said_vs_did at most 6; revealed_pattern at \
most 3; revised_target_criteria 4-5; caveats at most 3.
- revealed_pattern: what the company's ACTUAL deals suggest about the kind of \
deal it does (size, structure, business type), labeled as a hypothesis.
- revised_target_criteria: criteria for a fitting acquisition, updated for what \
the company actually does, each tied to evidence.

Record your answer by calling the record_trajectory tool.
"""

_STR = {"type": "string"}
_YEAR = _STR  # a label such as "FY2025"

TRAJECTORY_SCHEMA = _obj(
    company=_STR,
    bottom_line=_STR,
    changes=_arr(
        _obj(
            theme=_STR,
            change={
                "type": "string",
                "enum": ["new", "dropped", "strengthened", "softened", "shifted"],
            },
            year=_YEAR,
            description=_STR,
            evidence_year=_YEAR,
            evidence_quote=_STR,
        )
    ),
    said_vs_did=_arr(
        _obj(
            stated_priority=_STR,
            stated_in=_YEAR,
            what_filings_show=_STR,
            verdict={
                "type": "string",
                "enum": ["backed_by_action", "partly_backed", "no_visible_action", "contradicted"],
            },
            confidence={"type": "string", "enum": ["high", "medium", "low"]},
            evidence_year=_YEAR,
            evidence_quote=_STR,
        )
    ),
    revealed_pattern=_arr(_STR),
    revised_target_criteria=_arr(_obj(criterion=_STR, rationale=_STR)),
    caveats=_arr(_STR),
)

TRAJECTORY_TOOL = {
    "name": "record_trajectory",
    "description": "Record the multi-year strategy comparison.",
    "input_schema": TRAJECTORY_SCHEMA,
    "strict": True,
}

ALWAYS_CAVEAT = (
    "Based only on what each 10-K discloses; smaller or undisclosed deals may be missing."
)

VERDICT_ORDER = ["backed_by_action", "partly_backed", "no_visible_action", "contradicted"]

VERDICT_LABELS = {
    "backed_by_action": "Followed through",
    "partly_backed": "Partly followed through",
    "no_visible_action": "No matching action found",
    "contradicted": "Went the other way",
}

CHANGE_ORDER = ["new", "strengthened", "shifted", "softened", "dropped"]


def year_key(label: str) -> int:
    """Sort key for labels like 'FY2024'; unknown labels sort last."""
    digits = "".join(ch for ch in str(label) if ch.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else 9999


def ordered_changes(d: dict) -> list[dict]:
    """Changes oldest year first, so the timeline reads in the order things happened."""
    return sorted(
        d["changes"],
        key=lambda c: (
            year_key(c["year"]),
            CHANGE_ORDER.index(c["change"]) if c["change"] in CHANGE_ORDER else 99,
        ),
    )


def grouped_said_vs_did(d: dict) -> list[tuple[str, list[dict]]]:
    """Said-vs-did items grouped by outcome (best first), each group oldest 'said in' first."""
    groups = []
    for verdict in VERDICT_ORDER:
        items = sorted(
            (s for s in d["said_vs_did"] if s["verdict"] == verdict),
            key=lambda s: year_key(s["stated_in"]),
        )
        if items:
            groups.append((verdict, items))
    other = [s for s in d["said_vs_did"] if s["verdict"] not in VERDICT_ORDER]
    if other:
        groups.append(("unclear", other))
    return groups


def scorecard(d: dict) -> list[tuple[str, int]]:
    """(verdict, count) for each outcome that occurs, best first."""
    return [(v, len(items)) for v, items in grouped_said_vs_did(d)]


def _clean_profile(p: Profile) -> dict:
    """Compact view of one year's profile for the model; unverified quotes are dropped."""
    out = {
        "year": p.filing.get("label", "?"),
        "period_end": p.filing.get("period", "?"),
        "strategy_summary": p.data.get("strategy_summary", ""),
    }
    for field, main in QUOTED_FIELDS.items():
        out[field] = [
            {main: item[main], "quote": item["quote"] if item.get("quote_verified", True) else ""}
            for item in p.data.get(field, [])
        ]
    return out


def build_prompt(profiles: list[Profile]) -> str:
    years = [_clean_profile(p) for p in profiles]
    labels = ", ".join(y["year"] for y in years)
    return (
        f"Profiles for {labels} (oldest first):\n"
        + json.dumps(years, indent=1)
        + "\n\nCompare the years."
    )


def _corpora(profiles: list[Profile]) -> dict[str, str]:
    """Normalized text of each year's verified quotes, for checking cited evidence."""
    corpora = {}
    for p in profiles:
        parts = [
            item["quote"]
            for field in QUOTED_FIELDS
            for item in p.data.get(field, [])
            if item.get("quote") and item.get("quote_verified", True)
        ]
        corpora[p.filing.get("label", "?")] = _normalize_text(" ".join(parts))
    return corpora


def verify_evidence(data: dict, profiles: list[Profile]) -> dict:
    """Flag any cited quote that is not one of the verified quotes for the cited year."""
    corpora = _corpora(profiles)
    everything = " ".join(corpora.values())
    for field in ("changes", "said_vs_did"):
        for item in data.get(field, []):
            quote = _normalize_text(item.get("evidence_quote", ""))
            haystack = corpora.get(item.get("evidence_year", ""), everything)
            item["quote_verified"] = (not quote) or quote in haystack
    return data


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _item(value, main_key: str, keys: list[str]) -> dict:
    obj = dict(value) if isinstance(value, dict) else {main_key: str(value)}
    return {k: str(obj.get(k, "") or "") for k in keys} | {
        k: v for k, v in obj.items() if k not in keys
    }


def normalize(data: dict) -> dict:
    d = clean_text(dict(data))
    d["company"] = str(d.get("company") or "Unknown company")
    d["bottom_line"] = str(d.get("bottom_line") or "Not discussed")
    d["changes"] = [
        _item(x, "description", ["theme", "change", "year", "description", "evidence_year", "evidence_quote"])
        for x in _as_list(d.get("changes"))
    ]
    for c in d["changes"]:  # tolerate an older shape that used a "years" range
        if not c["year"] and c.get("years"):
            c["year"] = str(c["years"]).replace("to", "-").split("-")[-1].strip()
    d["said_vs_did"] = [
        _item(
            x,
            "stated_priority",
            ["stated_priority", "stated_in", "what_filings_show", "verdict", "confidence",
             "evidence_year", "evidence_quote"],
        )
        for x in _as_list(d.get("said_vs_did"))
    ]
    d["revealed_pattern"] = [str(x) for x in _as_list(d.get("revealed_pattern"))]
    d["revised_target_criteria"] = [
        _item(x, "criterion", ["criterion", "rationale"])
        for x in _as_list(d.get("revised_target_criteria"))
    ]
    d["caveats"] = [str(x) for x in _as_list(d.get("caveats"))]
    return d


@dataclass
class Trajectory:
    data: dict
    years: list[str]

    def to_json(self) -> str:
        return json.dumps({"years": self.years, **self.data}, indent=2)

    def to_markdown(self, evidence: bool = False) -> str:
        return render_markdown(self.data, self.years, evidence=evidence)


def build_trajectory(
    profiles: list[Profile], model: str = DEFAULT_MODEL, api_key: str | None = None
) -> Trajectory:
    """Profiles must be ordered oldest to newest. Uses `api_key` or ANTHROPIC_API_KEY."""
    if len(profiles) < 2:
        raise ValueError("Need at least two years of filings to compare.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        tools=[TRAJECTORY_TOOL],
        messages=[{"role": "user", "content": build_prompt(profiles)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            data = verify_evidence(normalize(dict(block.input)), profiles)
            return Trajectory(data, [p.filing.get("label", "?") for p in profiles])
    raise RuntimeError("The model did not return a comparison. Try again.")


DISCLAIMER = (
    "*Hypotheses for discussion, generated by AI from public filings. It can contain "
    "errors. Not a prediction, and not a recommendation to buy or sell any company "
    "or security.*"
)


def _cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def render_markdown(d: dict, years: list[str] | None = None, evidence: bool = False) -> str:
    """One-page comparison. Evidence quotes show with evidence=True; unverified ones always."""

    def _ev(item: dict) -> str:
        q = item.get("evidence_quote", "")
        verified = item.get("quote_verified", True)
        if not q or (verified and not evidence):
            return ""
        flag = "" if verified else " **[quote not verified]**"
        return f' "{q}" ({item.get("evidence_year") or "?"}){flag}'

    d = normalize(d)
    span = f" ({years[0]} to {years[-1]})" if years else ""
    lines = [
        f"# {d['company']} - strategy trajectory{span}",
        "",
        f"**Bottom line:** {d['bottom_line']}",
        "",
        "## What changed, in order",
    ]
    if d["changes"]:
        lines += ["| When | Change | Theme | What changed |", "|---|---|---|---|"]
        for c in ordered_changes(d):
            lines.append(
                f"| {_cell(c['year'] or '?')} | {_cell(c['change'].capitalize())} "
                f"| {_cell(c['theme'])} | {_cell(c['description'] + _ev(c))} |"
            )
    else:
        lines.append("- No clear changes found")
    lines += ["", "## Said vs. did"]
    groups = grouped_said_vs_did(d)
    if groups:
        counts = ", ".join(
            f"{n} {VERDICT_LABELS.get(v, 'unclear').lower()}" for v, n in scorecard(d)
        )
        lines += [f"*{len(d['said_vs_did'])} priorities tested: {counts}.*", ""]
        for verdict, items in groups:
            lines += [
                f"### {VERDICT_LABELS.get(verdict, 'Unclear')} ({len(items)})",
                "| Said in | Stated priority | What the filings show | Confidence |",
                "|---|---|---|---|",
            ]
            for s in items:
                lines.append(
                    f"| {_cell(s['stated_in'])} | {_cell(s['stated_priority'])} "
                    f"| {_cell(s['what_filings_show'] + _ev(s))} | {_cell(s['confidence'] or 'n/a')} |"
                )
            lines.append("")
    else:
        lines.append("- Not enough information")
    lines += [
        "",
        "## What the actual deals suggest (hypotheses)",
        *([f"- {x}" for x in d["revealed_pattern"]] or ["- Not enough information"]),
        "",
        "## Target criteria, revised for what the company actually does",
        *(
            [f"- **{c['criterion'].rstrip('. ')}**: {c['rationale']}" for c in d["revised_target_criteria"]]
            or ["- Not enough information"]
        ),
        "",
        "## Caveats",
        *[f"- {x}" for x in [*d["caveats"], ALWAYS_CAVEAT]],
        "",
        "---",
        DISCLAIMER,
    ]
    return "\n".join(lines)
