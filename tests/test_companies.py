from deal_fit.companies import (
    CompanyIndex,
    fallback_options,
    label,
    options_from_sec,
    pretty_name,
    ticker_from_label,
)


def test_pretty_name_title_cases_sec_capitals():
    assert pretty_name("GOLDMAN SACHS GROUP INC") == "Goldman Sachs Group Inc"
    assert pretty_name("JPMORGAN CHASE & CO") == "JPMorgan Chase & Co"
    assert pretty_name("BANK OF AMERICA CORP /DE/") == "Bank of America Corp"  # state tag dropped
    assert pretty_name("Walmart Inc.") == "Walmart Inc."  # already mixed case


def test_options_keep_sec_order_and_drop_duplicates_and_blanks():
    rows = [
        {"ticker": "AAA", "title": "ALPHA CORP"},
        {"ticker": "BBB", "title": "BETA INC"},
        {"ticker": "AAA", "title": "ALPHA CORP"},
        {"ticker": "", "title": "NO TICKER"},
    ]
    assert list(options_from_sec(rows).values()) == ["AAA", "BBB"]


def test_ticker_round_trips_through_the_label():
    for text in ("Goldman Sachs Group Inc  (GS)", "Berkshire Hathaway Inc.  (BRK-B)"):
        assert ticker_from_label(text) in {"GS", "BRK-B"}
    assert ticker_from_label(label("GS", "GOLDMAN SACHS GROUP INC")) == "GS"
    assert ticker_from_label(None) == ""


def _index():
    rows = [
        {"ticker": "GOOGL", "title": "Alphabet Inc."},
        {"ticker": "SPGI", "title": "S&P GLOBAL INC."},
        {"ticker": "GS", "title": "GOLDMAN SACHS GROUP INC"},
        {"ticker": "GSK", "title": "GSK PLC"},
        {"ticker": "JPM", "title": "JPMORGAN CHASE & CO"},
        {"ticker": "BAC", "title": "BANK OF AMERICA CORP /DE/"},
        {"ticker": "BK", "title": "BANK OF NEW YORK MELLON CORP"},
        {"ticker": "MS", "title": "MORGAN STANLEY"},
    ]
    return CompanyIndex(options_from_sec(rows))


def test_search_prefers_names_that_start_with_the_text_and_skips_fuzzy_noise():
    results = _index().search("gol")
    assert results == ["Goldman Sachs Group Inc  (GS)"]  # not Alphabet or S&P Global


def test_search_ranks_exact_ticker_then_ticker_prefix_then_name():
    results = _index().search("gs")
    assert results[0].endswith("(GS)") and results[1].endswith("(GSK)")


def test_search_matches_any_word_and_multiple_words():
    idx = _index()
    assert "Morgan Stanley  (MS)" in idx.search("stan")
    assert idx.search("goldman sachs") == ["Goldman Sachs Group Inc  (GS)"]
    assert [r.split("(")[-1] for r in idx.search("bank")] == ["BAC)", "BK)"]  # SEC order kept
    assert idx.search("zzzz") == []


def test_empty_search_shows_suggestions_that_exist():
    sugg = _index().search("")
    assert any("(GS)" in s for s in sugg) and any("(JPM)" in s for s in sugg)


def test_fallback_list_is_searchable_by_name_or_ticker():
    labels = list(fallback_options())
    assert any("Goldman" in x and "(GS)" in x for x in labels)
    assert len(labels) > 50
