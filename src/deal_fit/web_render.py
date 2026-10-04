"""Executive report layout: HTML for the web page and for a downloadable one-page file."""

from __future__ import annotations

import html
import re

from . import profile as profile_mod
from . import trajectory as traj
from .trajectory import VERDICT_LABELS, grouped_said_vs_did, ordered_changes

NAVY, SLATE = "#0B2545", "#5B6776"
# verdict -> (tint, text) colors
VERDICT_COLORS = {
    "backed_by_action": ("#E6F4EC", "#1E7B4F"),
    "partly_backed": ("#FBF1DC", "#8A5A00"),
    "no_visible_action": ("#ECEFF3", "#4A5666"),
    "contradicted": ("#FBE7E8", "#A3202A"),
    "unclear": ("#ECEFF3", "#4A5666"),
}
CHANGE_COLORS = {
    "new": ("#E8F0FB", "#1F4E8C"),
    "strengthened": ("#E6F4EC", "#1E7B4F"),
    "shifted": ("#ECEFF3", "#4A5666"),
    "softened": ("#FBF1DC", "#8A5A00"),
    "dropped": ("#FBE7E8", "#A3202A"),
}

CSS = f"""
<style>
.df{{font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;color:#1B2430;line-height:1.5;max-width:940px;margin:0 auto}}
.df *{{box-sizing:border-box}}
.df-eyebrow{{font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;color:{SLATE};font-weight:600}}
.df-title{{font-size:2.15rem;font-weight:700;color:{NAVY};margin:.15rem 0 1rem;letter-spacing:-.015em;line-height:1.15}}
.df-bottom{{border-left:4px solid {NAVY};background:#F3F6FA;padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:6px}}
.df-label{{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:{SLATE};font-weight:700}}
.df-bottom p{{font-size:1.13rem;font-weight:500;margin:.25rem 0 0;color:#14202F}}
.df h2{{font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:{NAVY};border-bottom:1px solid #D9DFE7;padding-bottom:7px;margin:36px 0 14px;font-weight:700}}
.df-score{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}}
.df-chip{{padding:5px 12px;border-radius:999px;font-size:.84rem;font-weight:600}}
.df-year{{display:grid;grid-template-columns:84px 1fr;gap:18px;padding:16px 0;border-top:1px solid #E6EAF0}}
.df h2+.df-year{{border-top:0}}
.df-year-label{{font-weight:700;color:{NAVY};font-size:1.08rem}}
.df-item{{margin-bottom:14px}}
.df-item:last-child{{margin-bottom:0}}
.df-item p{{margin:3px 0 0;color:#2B3644}}
.df-tag{{display:inline-block;font-size:.68rem;letter-spacing:.07em;text-transform:uppercase;font-weight:700;padding:2px 8px;border-radius:4px;margin-right:8px;vertical-align:1px}}
.df-theme{{font-weight:650;color:{NAVY}}}
.df-quote{{font-size:.84rem;color:{SLATE};border-left:2px solid #D9DFE7;padding-left:10px;margin-top:6px;font-style:italic}}
.df-flag{{color:#A3202A;font-weight:700;font-style:normal}}
.df-group-head{{display:flex;align-items:center;gap:9px;font-weight:700;color:{NAVY};margin:22px 0 4px;font-size:1.02rem}}
.df-group-head span.df-count{{font-weight:600;font-size:.8rem;color:{SLATE}}}
.df-dot{{width:11px;height:11px;border-radius:50%;display:inline-block}}
.df-row{{display:grid;grid-template-columns:36% 1fr;gap:22px;padding:11px 0;border-top:1px solid #EDF0F4}}
.df-priority{{font-weight:600;color:#14202F}}
.df-meta{{display:block;font-size:.78rem;color:{SLATE};font-weight:500;margin-top:2px}}
.df-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.df-card{{border:1px solid #E1E6ED;border-radius:10px;padding:14px 18px;background:#fff}}
.df-card h3{{font-size:.74rem;text-transform:uppercase;letter-spacing:.1em;color:{SLATE};margin:0 0 8px;font-weight:700}}
.df-card ul,.df-list{{margin:0;padding-left:18px}}
.df-card li,.df-list li{{margin-bottom:7px}}
.df-crit{{display:grid;grid-template-columns:30px 1fr;gap:12px;padding:11px 0;border-top:1px solid #EDF0F4}}
.df-num{{width:24px;height:24px;border-radius:50%;background:{NAVY};color:#fff;text-align:center;font-size:.8rem;line-height:24px;font-weight:700}}
.df-crit p{{margin:2px 0 0;color:#2B3644}}
.df-conf{{font-size:.7rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{SLATE};margin-left:6px}}
.df details{{margin-top:26px;color:{SLATE};font-size:.86rem}}
.df summary{{cursor:pointer;font-weight:600}}
.df-foot{{margin-top:30px;padding-top:12px;border-top:1px solid #D9DFE7;font-size:.76rem;color:#6B7785}}
@media (max-width:720px){{.df-grid,.df-row,.df-year{{grid-template-columns:1fr}}.df-title{{font-size:1.7rem}}}}
@media print{{.df{{max-width:none}}.df h2{{break-after:avoid}}.df-row,.df-item,.df-card{{break-inside:avoid}}}}
</style>
"""


def _e(text) -> str:
    """Escape for HTML. '$' becomes an entity so no markdown/math parser can touch it."""
    return html.escape(str(text), quote=False).replace("$", "&#36;")


def _strip_label(text: str, *labels: str) -> str:
    """Drop leading 'Inference:' / 'Hypothesis:' (the section heading already says so)."""
    for label in labels:
        text = re.sub(rf"^\s*{label}\s*:\s*", "", text, flags=re.I)
    return text[:1].upper() + text[1:]


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _quote(text: str, year: str, verified: bool, evidence: bool) -> str:
    """Supporting quote. Hidden unless evidence is on; an unverified one always shows a flag."""
    if not text or (verified and not evidence):
        return ""
    flag = "" if verified else '<span class="df-flag">Quote not verified. </span>'
    where = f" ({_e(year)})" if year else ""
    return f'<div class="df-quote">{flag}&ldquo;{_e(text)}&rdquo;{where}</div>'


def _chip(label: str, colors: tuple[str, str]) -> str:
    bg, fg = colors
    return f'<span class="df-chip" style="background:{bg};color:{fg}">{_e(label)}</span>'


def _footer(disclaimer: str) -> str:
    return f'<div class="df-foot">{_e(disclaimer.strip("*"))}</div>'


# ---- multi-year comparison ---------------------------------------------------


def trajectory_html(d: dict, years: list[str] | None = None, evidence: bool = False) -> str:
    d = traj.normalize(d)
    span = f" &middot; {_e(years[0])}&ndash;{_e(years[-1])}" if years else ""
    out = [
        '<div class="df">',
        f'<div class="eyebrow df-eyebrow">Strategy trajectory{span}</div>',
        f'<div class="df-title">{_e(d["company"])}</div>',
        f'<div class="df-bottom"><div class="df-label">Bottom line</div><p>{_e(d["bottom_line"])}</p></div>',
    ]

    # What changed, oldest year first
    out.append("<h2>What changed, year by year</h2>")
    changes = ordered_changes(d)
    if changes:
        by_year: dict[str, list[dict]] = {}
        for c in changes:
            by_year.setdefault(c["year"] or "?", []).append(c)
        for year, items in by_year.items():
            rows = []
            for c in items:
                bg, fg = CHANGE_COLORS.get(c["change"], CHANGE_COLORS["shifted"])
                rows.append(
                    '<div class="df-item">'
                    f'<span class="df-tag" style="background:{bg};color:{fg}">{_e(c["change"])}</span>'
                    f'<span class="df-theme">{_e(c["theme"])}</span>'
                    f'<p>{_e(c["description"])}</p>'
                    + _quote(c["evidence_quote"], c["evidence_year"], c.get("quote_verified", True), evidence)
                    + "</div>"
                )
            out.append(
                f'<div class="df-year"><div class="df-year-label">{_e(year)}</div>'
                f'<div>{"".join(rows)}</div></div>'
            )
    else:
        out.append("<p>No clear changes found.</p>")

    # Said vs. did, grouped by outcome
    out.append("<h2>Said vs. did</h2>")
    groups = grouped_said_vs_did(d)
    if groups:
        total = len(d["said_vs_did"])
        chips = "".join(
            _chip(f"{n} {VERDICT_LABELS.get(v, 'Unclear').lower()}", VERDICT_COLORS.get(v, VERDICT_COLORS["unclear"]))
            for v, n in traj.scorecard(d)
        )
        out.append(
            f'<div class="df-label">{_plural(total, "priority", "priorities")} tested against what the filings show</div>'
            f'<div class="df-score">{chips}</div>'
        )
        for verdict, items in groups:
            tint, fg = VERDICT_COLORS.get(verdict, VERDICT_COLORS["unclear"])
            out.append(
                f'<div class="df-group-head"><span class="df-dot" style="background:{fg}"></span>'
                f'{_e(VERDICT_LABELS.get(verdict, "Unclear"))}<span class="df-count">{len(items)}</span></div>'
            )
            for s in items:
                conf = f' &middot; {_e(s["confidence"])} confidence' if s["confidence"] else ""
                out.append(
                    '<div class="df-row">'
                    f'<div class="df-priority">{_e(s["stated_priority"])}'
                    f'<span class="df-meta">Said in {_e(s["stated_in"] or "?")}{conf}</span></div>'
                    f'<div>{_e(s["what_filings_show"])}'
                    + _quote(s["evidence_quote"], s["evidence_year"], s.get("quote_verified", True), evidence)
                    + "</div></div>"
                )
    else:
        out.append("<p>Not enough information.</p>")

    if d["revealed_pattern"]:
        out.append("<h2>What the actual deals suggest</h2><ul class=\"df-list\">")
        out += [f"<li>{_e(_strip_label(x, 'Hypothesis'))}</li>" for x in d["revealed_pattern"]]
        out.append("</ul>")

    out.append("<h2>Target criteria, based on what the company actually does</h2>")
    for i, c in enumerate(d["revised_target_criteria"], 1):
        out.append(
            f'<div class="df-crit"><div class="df-num">{i}</div><div>'
            f'<div class="df-theme">{_e(c["criterion"].rstrip(". "))}</div><p>{_e(c["rationale"])}</p></div></div>'
        )
    if not d["revised_target_criteria"]:
        out.append("<p>Not enough information.</p>")

    caveats = "".join(f"<li>{_e(x)}</li>" for x in [*d["caveats"], traj.ALWAYS_CAVEAT])
    out.append(f'<details><summary>Caveats</summary><ul class="df-list">{caveats}</ul></details>')
    out.append(_footer(traj.DISCLAIMER))
    out.append("</div>")
    return CSS + "".join(out)


# ---- one-year profile ----------------------------------------------------------


def _card(title: str, items: list[dict], key: str, evidence: bool) -> str:
    if not items:
        body = "<p>Not discussed.</p>"
    else:
        lis = "".join(
            f"<li>{_e(i[key])}"
            + _quote(i.get("quote", ""), "", i.get("quote_verified", True), evidence)
            + "</li>"
            for i in items
        )
        body = f"<ul>{lis}</ul>"
    return f'<div class="df-card"><h3>{_e(title)}</h3>{body}</div>'


def profile_html(d: dict, filing: dict | None = None, evidence: bool = False) -> str:
    d = profile_mod.normalize(d)
    filing = filing or {}
    bits = [filing.get("label") or filing.get("form"), f"filed {filing['filed']}" if filing.get("filed", "?") != "?" else ""]
    source = " &middot; ".join(_e(b) for b in bits if b)
    out = [
        '<div class="df">',
        f'<div class="eyebrow df-eyebrow">Acquirer profile{" &middot; " + source if source else ""}</div>',
        f'<div class="df-title">{_e(d["company"])}</div>',
        f'<div class="df-bottom"><div class="df-label">Strategy in brief</div><p>{_e(d["strategy_summary"])}</p></div>',
        "<h2>What it says and does</h2>",
        '<div class="df-grid">',
        _card("Stated priorities", d["stated_priorities"], "priority", evidence),
        _card("Where it is investing", d["capability_investments"], "area", evidence),
        _card("Constraints on deals", d["constraints"], "constraint", evidence),
        _card("Deals and other actions", d["acquisition_history"], "description", evidence),
        "</div>",
        "<h2>Possible capability gaps (our inference, not the company&rsquo;s words)</h2>",
    ]
    for g in d["capability_gap_hypotheses"]:
        conf = f'<span class="df-conf">{_e(g["confidence"])} confidence</span>' if g["confidence"] else ""
        out.append(
            f'<div class="df-item"><span class="df-theme">{_e(_strip_label(g["gap"], "Inference"))}</span>{conf}'
            f'<p>{_e(_strip_label(g["reasoning"], "Inference"))}</p></div>'
        )
    if not d["capability_gap_hypotheses"]:
        out.append("<p>Not enough information.</p>")
    out.append("<h2>Suggested target criteria</h2>")
    for i, c in enumerate(d["target_criteria"], 1):
        out.append(
            f'<div class="df-crit"><div class="df-num">{i}</div><div>'
            f'<div class="df-theme">{_e(c["criterion"].rstrip(". "))}</div>'
            f'<p>{_e(_strip_label(c["rationale"], "Inference"))}</p></div></div>'
        )
    if d["open_questions"]:
        out.append('<h2>Open questions</h2><ul class="df-list">')
        out += [f"<li>{_e(q)}</li>" for q in d["open_questions"]]
        out.append("</ul>")
    out.append(_footer(profile_mod.DISCLAIMER))
    out.append("</div>")
    return CSS + "".join(out)


def report_document(inner_html: str, title: str) -> str:
    """A self-contained HTML page: open it in a browser and print or save as PDF."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title>"
        '<style>body{margin:0;padding:32px 20px;background:#fff}</style></head>'
        f"<body>{inner_html}</body></html>"
    )
