"""Build a grounded acquirer profile and target criteria from public filing text."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

import anthropic

DEFAULT_MODEL = os.environ.get("DEAL_FIT_MODEL", "claude-sonnet-5-5")

SYSTEM_PROMPT = """\
You are a corporate-development research assistant. You read an acquirer's own \
public annual report (10-K) and describe its strategy so a deal team can think \
about what kinds of acquisitions would fit.

Rules:
- Use ONLY the filing text provided. Never use outside knowledge. You may name \
companies that the filing itself names in past or pending deals, but never \
propose or name new potential acquisition targets.
- Every item in stated_priorities, capability_investments, constraints and \
acquisition_history needs a "quote": an exact, word-for-word passage of at most \
30 words copied from the filing. Use "" only if no passage supports it. Never \
paraphrase inside a quote.
- capability_gap_hypotheses and target_criteria are YOUR inferences. Label them \
as such through the reasoning, give a confidence, and tie each to the priorities \
or constraints it comes from.
- Long sections are condensed to their most relevant paragraphs. If something \
is not in the text you see, say "Not discussed in the text provided"; never say \
a document was truncated or call it an excerpt.
- capability_investments lists only capabilities, products or platforms the \
filing says the company is investing in or building. Reorganizations are not \
investments.
- acquisition_history covers deals AND other significant actions the filing \
reports the company has taken: acquisitions, divestitures, partnerships, \
portfolio reductions or wind-downs, restructurings. Include figures when the \
filing gives them (for example how a portfolio changed from one year to the \
next). Begin each description with the type: "Acquired", "Sold", "Partnered", \
"Reduced" or "Restructured".
- These are hypotheses for discussion. Do NOT recommend buying any company, and \
do not give investment advice.
- Write for a busy senior executive: every item is ONE sentence of at most 30 \
words. Limits: stated_priorities 3-4; acquisition_history at most 5; \
capability_investments, constraints, capability_gap_hypotheses at most 3 each; \
target_criteria 4-5; open_questions at most 3.

Record your answer by calling the record_profile tool.
"""

_STR = {"type": "string"}


def _obj(**props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


PROFILE_SCHEMA = _obj(
    company=_STR,
    strategy_summary=_STR,
    stated_priorities=_arr(_obj(priority=_STR, quote=_STR)),
    capability_investments=_arr(_obj(area=_STR, quote=_STR)),
    constraints=_arr(_obj(constraint=_STR, quote=_STR)),
    acquisition_history=_arr(_obj(description=_STR, quote=_STR)),
    capability_gap_hypotheses=_arr(
        _obj(
            gap=_STR,
            reasoning=_STR,
            confidence={"type": "string", "enum": ["high", "medium", "low"]},
        )
    ),
    target_criteria=_arr(_obj(criterion=_STR, rationale=_STR)),
    open_questions=_arr(_STR),
)

PROFILE_TOOL = {
    "name": "record_profile",
    "description": "Record the structured acquirer profile.",
    "input_schema": PROFILE_SCHEMA,
    "strict": True,
}

# Changes whenever the prompt or schema changes, so cached profiles go stale.
PROMPT_VERSION = hashlib.sha1(
    (SYSTEM_PROMPT + json.dumps(PROFILE_SCHEMA, sort_keys=True)).encode()
).hexdigest()[:10]

SECTION_TITLES = {
    "business": "Item 1. Business",
    "risk_factors": "Item 1A. Risk Factors",
    "mdna": "Item 7. Management's Discussion and Analysis",
}

# Fields whose items carry a verbatim quote that we check against the filing.
QUOTED_FIELDS = {
    "stated_priorities": "priority",
    "capability_investments": "area",
    "constraints": "constraint",
    "acquisition_history": "description",
}


def _normalize_text(text: str) -> str:
    text = (
        text.replace("“", '"').replace("”", '"')
        .replace("‘", "'").replace("’", "'")
        .replace("–", "-").replace("—", "-")
    )
    return re.sub(r"[^a-z0-9 ]+", "", " ".join(text.lower().split()))


def clean_text(value):
    """Repair stray replacement characters (U+FFFD) the model occasionally emits.

    Between digits it was almost certainly a range dash ("$2<?>3 billion"), so it
    becomes an en dash; anywhere else it is dropped.
    """
    if isinstance(value, str):
        value = re.sub(r"(?<=\d)�(?=\d)", "–", value)
        return value.replace("�", "")
    if isinstance(value, list):
        return [clean_text(v) for v in value]
    if isinstance(value, dict):
        return {k: clean_text(v) for k, v in value.items()}
    return value


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _item(value, main_key: str, keys: list[str]) -> dict:
    """Coerce one list item into a dict with all expected keys."""
    obj = dict(value) if isinstance(value, dict) else {main_key: str(value)}
    return {k: str(obj.get(k, "") or "") for k in keys} | {
        k: v for k, v in obj.items() if k not in keys
    }


def normalize(data: dict) -> dict:
    """Coerce slightly-off model output into the shape the renderer expects."""
    d = clean_text(dict(data))
    d["company"] = str(d.get("company") or "Unknown company")
    d["strategy_summary"] = str(d.get("strategy_summary") or "Not discussed")
    for field, main in QUOTED_FIELDS.items():
        d[field] = [_item(x, main, [main, "quote"]) for x in _as_list(d.get(field))]
    d["capability_gap_hypotheses"] = [
        _item(x, "gap", ["gap", "reasoning", "confidence"])
        for x in _as_list(d.get("capability_gap_hypotheses"))
    ]
    d["target_criteria"] = [
        _item(x, "criterion", ["criterion", "rationale"])
        for x in _as_list(d.get("target_criteria"))
    ]
    d["open_questions"] = [str(x) for x in _as_list(d.get("open_questions"))]
    return d


def verify_quotes(data: dict, source: str) -> dict:
    """Mark each quote as found (or not) word-for-word in the filing text."""
    haystack = _normalize_text(source)
    for field in QUOTED_FIELDS:
        for item in data.get(field, []):
            quote = _normalize_text(item.get("quote", ""))
            item["quote_verified"] = (not quote) or quote in haystack
    return data


@dataclass
class Profile:
    data: dict
    filing: dict

    def to_json(self) -> str:
        return json.dumps({"filing": self.filing, **self.data}, indent=2)

    def to_markdown(self, evidence: bool = False) -> str:
        return render_markdown(self.data, self.filing, evidence=evidence)


def build_prompt(sections: dict[str, str]) -> str:
    parts = [
        f"<{key} title=\"{SECTION_TITLES[key]}\">\n{text}\n</{key}>"
        for key, text in sections.items()
    ]
    return "\n\n".join(parts) + "\n\nBuild the acquirer profile from this filing."


def build_profile(
    sections: dict[str, str],
    filing: dict,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> Profile:
    """Uses `api_key` if given, otherwise ANTHROPIC_API_KEY from the environment."""
    if not sections:
        raise ValueError("No filing sections to analyze.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[PROFILE_TOOL],
        messages=[{"role": "user", "content": build_prompt(sections)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            data = normalize(dict(block.input))
            data = verify_quotes(data, "\n".join(sections.values()))
            return Profile(data, filing)
    raise RuntimeError("The model did not return a profile. Try again.")


DISCLAIMER = (
    "*Hypotheses for discussion, generated by AI from one public filing. It can "
    "contain errors. Not a recommendation to buy or sell any company or security.*"
)


def _bullets(items: list[str], empty: str = "- Not discussed") -> list[str]:
    return [f"- {i}" for i in items] if items else [empty]


def render_markdown(d: dict, filing: dict | None = None, evidence: bool = False) -> str:
    """One-page profile. With evidence=True, show the supporting quote for each item.

    Quotes are always checked; an unverified one is flagged even when hidden.
    """

    def _quote(item: dict) -> str:
        q = item.get("quote", "")
        verified = item.get("quote_verified", True)
        if not q or (verified and not evidence):
            return ""
        flag = "" if verified else " **[quote not found in filing]**"
        return f' - "{q}"{flag}'

    d = normalize(d)
    filing = filing or {}
    source = ""
    if filing:
        source = (
            f"*Source: {filing.get('form', '10-K')} for period ending "
            f"{filing.get('period', '?')}, filed {filing.get('filed', '?')}.*"
        )
    lines = [
        f"# {d.get('company', 'Unknown company')} - acquirer profile",
        source,
        "",
        f"**Strategy in brief:** {d.get('strategy_summary', 'Not discussed')}",
        "",
        "## Stated priorities",
        *_bullets([f"{i['priority']}{_quote(i)}" for i in d.get("stated_priorities", [])]),
        "",
        "## Where it says it is investing",
        *_bullets([f"{i['area']}{_quote(i)}" for i in d.get("capability_investments", [])]),
        "",
        "## Constraints",
        *_bullets([f"{i['constraint']}{_quote(i)}" for i in d.get("constraints", [])]),
        "",
        "## Deals and other actions described in the filing",
        *_bullets([f"{i['description']}{_quote(i)}" for i in d.get("acquisition_history", [])]),
        "",
        "## Possible capability gaps (our inference, not stated by the company)",
        *_bullets(
            [
                f"{i['gap']} *(confidence: {i['confidence'] or 'n/a'})* - {i['reasoning']}"
                for i in d.get("capability_gap_hypotheses", [])
            ]
        ),
        "",
        "## Suggested target criteria",
        *_bullets(
            [
                f"**{i['criterion'].rstrip('. ')}**: {i['rationale']}"
                for i in d.get("target_criteria", [])
            ]
        ),
        "",
        "## Open questions",
        *_bullets(d.get("open_questions", [])),
        "",
        "---",
        DISCLAIMER,
    ]
    return "\n".join(lines)
