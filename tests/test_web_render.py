from deal_fit.web_render import profile_html, report_document, trajectory_html

TRAJ = {
    "company": "Acme <Corp>",
    "bottom_line": "Bought for $665 million and $300 million.",
    "changes": [
        {"theme": "Late", "change": "new", "year": "FY2025", "description": "late thing"},
        {"theme": "Early", "change": "dropped", "year": "FY2023", "description": "early thing"},
        {"theme": "Mid", "change": "shifted", "year": "FY2024", "description": "mid thing"},
    ],
    "said_vs_did": [
        {"stated_priority": "P-partial", "stated_in": "FY2024", "what_filings_show": "some",
         "verdict": "partly_backed", "confidence": "low"},
        {"stated_priority": "P-done", "stated_in": "FY2023", "what_filings_show": "all",
         "verdict": "backed_by_action", "confidence": "high",
         "evidence_year": "FY2024", "evidence_quote": "we did it", "quote_verified": True},
    ],
    "revealed_pattern": ["Hypothesis: mid-sized deals."],
    "revised_target_criteria": [{"criterion": "Fee-based.", "rationale": "Fits."}],
}


def test_timeline_reads_oldest_to_newest():
    page = trajectory_html(TRAJ, ["FY2023", "FY2025"])
    assert page.index("early thing") < page.index("mid thing") < page.index("late thing")
    assert page.index(">FY2023<") < page.index(">FY2024<") < page.index(">FY2025<")


def test_said_vs_did_is_grouped_best_outcome_first_with_scorecard():
    page = trajectory_html(TRAJ)
    assert page.index("Followed through") < page.index("Partly followed through")
    assert "2 priorities tested" in page
    assert "1 followed through" in page and "1 partly followed through" in page


def test_text_is_escaped_and_dollar_signs_are_entities():
    page = trajectory_html(TRAJ)
    assert "Acme &lt;Corp&gt;" in page and "<Corp>" not in page
    assert "&#36;665 million" in page and "$665" not in page.split("</style>")[1]


def test_hypothesis_prefix_is_removed_under_a_hypothesis_heading():
    assert "<li>Mid-sized deals.</li>" in trajectory_html(TRAJ)  # prefix gone, capital restored


def test_quotes_hidden_by_default_shown_with_evidence_flagged_when_unverified():
    assert "we did it" not in trajectory_html(TRAJ)
    assert "we did it" in trajectory_html(TRAJ, evidence=True)
    bad = {**TRAJ, "said_vs_did": [{**TRAJ["said_vs_did"][1], "quote_verified": False}]}
    assert "Quote not verified" in trajectory_html(bad)  # even with evidence off


def test_profile_cards_and_inference_label():
    data = {
        "company": "Acme",
        "strategy_summary": "Advisory focus.",
        "stated_priorities": [{"priority": "Grow", "quote": "we grow", "quote_verified": True}],
        "capability_gap_hypotheses": [
            {"gap": "Inference: needs scale", "reasoning": "Inference: because", "confidence": "low"}
        ],
        "target_criteria": [{"criterion": "Capital-light.", "rationale": "Inference: rules"}],
    }
    page = profile_html(data, {"label": "FY2025", "filed": "2026-02-25"})
    for heading in ("Stated priorities", "Where it is investing", "Constraints on deals"):
        assert heading in page
    assert "FY2025" in page and "filed 2026-02-25" in page
    assert "Inference: needs scale" not in page and "Needs scale" in page
    assert "we grow" not in page and "we grow" in profile_html(data, evidence=True)


def test_report_document_is_a_standalone_printable_page():
    doc = report_document(trajectory_html(TRAJ), "Acme <x> - trajectory")
    assert doc.startswith("<!doctype html>") and "<title>Acme &lt;x&gt; - trajectory</title>" in doc
    assert "@media print" in doc
