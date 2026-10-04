from pathlib import Path

import pytest
import streamlit_searchbox
from streamlit.testing.v1 import AppTest

import deal_fit.edgar as edgar
import deal_fit.pipeline as pipeline
from deal_fit.edgar import Filing
from deal_fit.profile import Profile, normalize, verify_quotes

APP = str(Path(__file__).parent.parent / "app.py")
GS = "Goldman Sachs Group, Inc.  (GS)"


PICKED = {"company": None, "args": None, "kwargs": None}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Owner test@example.com")

    def no_sec():
        raise edgar.EdgarError("offline in tests")

    monkeypatch.setattr(edgar, "company_list", no_sec)  # forces the built-in company list

    # The type-ahead box is a browser component, so tests stand in for it: it records how
    # the app configured it and returns whichever company the test "picked".
    def fake_searchbox(*args, **kwargs):
        PICKED["args"], PICKED["kwargs"] = args, kwargs
        return PICKED["company"]

    PICKED["company"] = None
    monkeypatch.setattr(streamlit_searchbox, "st_searchbox", fake_searchbox)


def _start():
    return AppTest.from_file(APP).run(timeout=30)


def _analyze(at, company=GS, key="sk-test-key"):
    PICKED["company"] = company
    at.sidebar.text_input(key="api_key").set_value(key)
    return at.button(key="run").click().run(timeout=30)


def _html(at) -> str:
    return " ".join(str(getattr(e, "proto", e)) for e in at.get("html"))


def test_search_box_suggests_well_known_names_and_ranks_matches():
    _start()
    search = PICKED["args"][0]
    assert any("Goldman" in s for s in PICKED["kwargs"]["default_options"])
    assert "Goldman" in search("gol")[0]  # name match first, not fuzzy noise
    assert "(GS)" in search("gs")[0]  # ticker match


def test_missing_key_shows_message():
    at = _start()
    PICKED["company"] = GS
    at = at.button(key="run").click().run(timeout=30)
    assert any("API key" in e.value for e in at.error)


def test_missing_company_shows_message():
    at = _analyze(_start(), company=None)
    assert any("Choose a company" in e.value for e in at.error)


def test_profile_flow_passes_the_visitors_key_and_renders_the_report(monkeypatch):
    seen = {}
    filing = Filing("Acme Corp", "ACME", "10-K", "2026-02-25", "2025-12-31", "u", "acc")
    data = verify_quotes(
        normalize(
            {
                "company": "Acme Corp",
                "strategy_summary": "Bought assets for $665 million plus $300 million.",
                "stated_priorities": [{"priority": "Grow advisory", "quote": "grow advisory"}],
            }
        ),
        "we will grow advisory",
    )

    def fake_profile_for(f, cache_dir, api_key=None, log=print, **kw):
        seen["key"], seen["ticker"] = api_key, f.ticker
        log("fake progress line")
        return Profile(data, {"label": f.label, "period": f.period, "filed": f.filed})

    def fake_resolve(query):
        seen["query"] = query
        return 1, "Acme Corp", "ACME"

    monkeypatch.setattr(edgar, "resolve_company", fake_resolve)
    monkeypatch.setattr(edgar, "list_10ks", lambda cik, name, sym, n=1: [filing])
    monkeypatch.setattr(pipeline, "profile_for", fake_profile_for)

    at = _analyze(_start(), key="sk-visitor-key")
    assert not at.exception
    assert seen["key"] == "sk-visitor-key"
    assert seen["query"] == "GS"  # ticker was pulled out of the dropdown label
    page = _html(at)
    assert "Acquirer profile" in page and "Bought assets for" in page and "&#36;665 million" in page
    assert "sk-visitor-key" not in page  # the key is never echoed onto the page
    assert "Not a recommendation to buy or sell" in page  # result carries its own disclaimer


def test_errors_are_friendly(monkeypatch):
    def boom(q):
        raise edgar.EdgarError("No SEC-registered company found for 'GS'. Try the ticker.")

    monkeypatch.setattr(edgar, "resolve_company", boom)
    at = _analyze(_start())
    assert any("No SEC-registered company" in e.value for e in at.error)
