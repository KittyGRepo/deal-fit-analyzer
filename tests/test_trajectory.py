from deal_fit.edgar import Filing
from deal_fit.profile import Profile, normalize as normalize_profile, verify_quotes
from deal_fit.trajectory import (
    build_prompt,
    render_markdown,
    verify_evidence,
)


def _profile(label: str, priority: str, quote: str, source: str) -> Profile:
    data = verify_quotes(
        normalize_profile(
            {
                "strategy_summary": f"{label} summary",
                "stated_priorities": [{"priority": priority, "quote": quote}],
                "acquisition_history": [
                    {"description": "Acquired Acme", "quote": "we acquired Acme"}
                ],
            }
        ),
        source + " we acquired Acme",
    )
    return Profile(data, {"label": label, "period": f"{label[2:]}-12-31"})


PROFILES = [
    _profile("FY2023", "Grow advisory", "we will grow advisory", "we will grow advisory"),
    _profile("FY2024", "Expand AI", "invest in AI", "invest in AI"),
]


def test_filing_label_comes_from_period_end():
    f = Filing("X", "X", "10-K", "2026-02-25", "2025-12-31", "u", "acc")
    assert f.label == "FY2025"


def _block(forms_dates):
    return {
        "form": [f for f, _ in forms_dates],
        "filingDate": [d for _, d in forms_dates],
        "reportDate": [d.replace("-02-", "-12-") for _, d in forms_dates],
        "accessionNumber": [f"0000-{i}" for i in range(len(forms_dates))],
        "primaryDocument": [f"doc{i}.htm" for i in range(len(forms_dates))],
    }


def test_list_10ks_reads_older_submission_files(monkeypatch):
    """Heavy filers' 'recent' list can hold just one 10-K; older ones are in extra files."""
    import deal_fit.edgar as edgar

    pages = {
        "main": {
            "filings": {
                "recent": _block([("424B2", "2026-09-01"), ("10-K", "2026-02-25")]),
                "files": [{"name": "old-1.json"}, {"name": "old-2.json"}],
            }
        },
        "old-1.json": _block([("10-Q", "2025-05-01"), ("10-K", "2025-02-27")]),
        "old-2.json": _block([("10-K", "2024-02-22")]),
    }

    class Resp:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_get(url):
        return Resp(pages["main"] if "CIK" in url else pages[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(edgar, "_get", fake_get)
    found = edgar.list_10ks(1, "Acme", "ACM", 3)
    assert [f.filed for f in found] == ["2026-02-25", "2025-02-27", "2024-02-22"]
    # stops reading older files once it has enough
    assert [f.filed for f in edgar.list_10ks(1, "Acme", "ACM", 2)] == ["2026-02-25", "2025-02-27"]


def test_prompt_contains_years_and_quotes_but_not_unverified_ones():
    bad = _profile("FY2025", "Made up", "invented quote", "something else")
    bad.data["stated_priorities"][0]["quote_verified"] = False
    prompt = build_prompt([*PROFILES, bad])
    assert "FY2023" in prompt and "we will grow advisory" in prompt
    assert "invented quote" not in prompt


def test_evidence_must_come_from_the_cited_year():
    data = {
        "changes": [
            {"evidence_year": "FY2024", "evidence_quote": "invest in AI"},
            {"evidence_year": "FY2023", "evidence_quote": "invest in AI"},
            {"evidence_year": "FY2024", "evidence_quote": "totally made up"},
        ],
        "said_vs_did": [],
    }
    flags = [c["quote_verified"] for c in verify_evidence(data, PROFILES)["changes"]]
    assert flags == [True, False, False]


def test_render_table_and_verdict_labels():
    data = {
        "company": "Acme Corp",
        "bottom_line": "Strategy shifted toward AI.",
        "changes": [
            {"theme": "AI", "change": "new", "year": "FY2024", "description": "AI added | big"}
        ],
        "said_vs_did": [
            {
                "stated_priority": "Grow advisory",
                "stated_in": "FY2023",
                "what_filings_show": "No matching deals.",
                "verdict": "no_visible_action",
                "confidence": "medium",
            }
        ],
    }
    md = render_markdown(data, ["FY2023", "FY2024"])
    assert "Acme Corp - strategy trajectory (FY2023 to FY2024)" in md
    assert "### No matching action found (1)" in md
    assert "1 priorities tested: 1 no matching action found" in md
    assert "AI added / big" in md  # pipe characters would break the table
    assert "smaller or undisclosed deals may be missing" in md
    assert "Not a prediction" in md


def _change(year, change="new", theme="t"):
    return {"theme": theme, "change": change, "year": year, "description": "d"}


def test_timeline_is_chronological_with_when_as_first_column():
    data = {
        "changes": [
            _change("FY2025", theme="late"),
            _change("FY2023", theme="early"),
            _change("FY2024", theme="middle"),
        ]
    }
    from deal_fit.trajectory import normalize, ordered_changes

    assert [c["theme"] for c in ordered_changes(normalize(data))] == ["early", "middle", "late"]
    md = render_markdown(data)
    assert "| When | Change | Theme | What changed |" in md
    assert md.index("early") < md.index("middle") < md.index("late")


def test_same_year_changes_sort_new_before_dropped():
    from deal_fit.trajectory import normalize, ordered_changes

    data = {"changes": [_change("FY2024", "dropped", "b"), _change("FY2024", "new", "a")]}
    assert [c["theme"] for c in ordered_changes(normalize(data))] == ["a", "b"]


def test_stray_replacement_characters_are_repaired():
    from deal_fit.trajectory import normalize

    d = normalize(
        {
            "bottom_line": "ok�",
            "revised_target_criteria": [
                {"criterion": "Deal size under $2�3 billion", "rationale": "x"}
            ],
        }
    )
    assert d["bottom_line"] == "ok"
    assert d["revised_target_criteria"][0]["criterion"] == "Deal size under $2–3 billion"


def test_old_years_range_still_gets_a_single_year():
    from deal_fit.trajectory import normalize

    c = normalize({"changes": [{"theme": "x", "change": "new", "years": "FY2023-FY2025"}]})
    assert c["changes"][0]["year"] == "FY2025"


def test_said_vs_did_groups_by_outcome_best_first_then_oldest():
    from deal_fit.trajectory import grouped_said_vs_did, normalize, scorecard

    def s(prio, year, verdict):
        return {"stated_priority": prio, "stated_in": year, "verdict": verdict}

    data = normalize(
        {
            "said_vs_did": [
                s("c", "FY2024", "partly_backed"),
                s("a", "FY2025", "backed_by_action"),
                s("b", "FY2023", "partly_backed"),
                s("d", "FY2023", "contradicted"),
            ]
        }
    )
    groups = grouped_said_vs_did(data)
    assert [g[0] for g in groups] == ["backed_by_action", "partly_backed", "contradicted"]
    assert [i["stated_priority"] for i in groups[1][1]] == ["b", "c"]  # FY2023 before FY2024
    assert scorecard(data) == [("backed_by_action", 1), ("partly_backed", 2), ("contradicted", 1)]


def test_unverified_evidence_is_flagged_even_when_hidden():
    data = {
        "changes": [
            {
                "theme": "AI",
                "change": "new",
                "year": "FY2024",
                "description": "x",
                "evidence_year": "FY2024",
                "evidence_quote": "fake",
                "quote_verified": False,
            }
        ]
    }
    assert "quote not verified" in render_markdown(data)


def test_render_tolerates_sloppy_data():
    md = render_markdown({"bottom_line": "ok", "changes": "just a string", "caveats": "one"})
    assert "just a string" in md and "one" in md
