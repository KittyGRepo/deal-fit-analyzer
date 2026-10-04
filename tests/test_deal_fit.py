from deal_fit.edgar import extract_section, extract_sections, html_to_text
from deal_fit.profile import normalize, render_markdown, verify_quotes

FILING = (
    "TABLE OF CONTENTS\nItem 1. Business\nItem 1A. Risk Factors\nItem 2. Properties\n"
    "Item 1. Business\n" + "We are a global firm focused on advisory. " * 100 + "\n"
    "Item 1A. Risk Factors\n" + "Regulation limits our capital. " * 100 + "\n"
    "Item 2. Properties\nOffices.\n"
    "Item 7. Management's Discussion\n" + "Revenue grew on strong demand. " * 100 + "\n"
    "Item 7A. Market Risk\nRates.\n"
)


def test_extract_skips_table_of_contents():
    business = extract_section(FILING, "1", ["1a", "2"])
    assert "global firm focused on advisory" in business
    assert len(business) > 3000


def test_extract_sections_finds_all_three():
    sections = extract_sections(FILING)
    assert set(sections) == {"business", "risk_factors", "mdna"}
    assert "Regulation limits" in sections["risk_factors"]


def test_html_to_text_drops_scripts_and_hidden_header():
    html = "<html><script>x=1</script><ix:header>hidden</ix:header><p>Item 1. Business</p></html>"
    text = html_to_text(html)
    assert "hidden" not in text and "x=1" not in text and "Item 1. Business" in text


def test_quote_verification_flags_paraphrase():
    data = normalize(
        {
            "stated_priorities": [
                {"priority": "Grow advisory", "quote": "focused on advisory"},
                {"priority": "Invent", "quote": "we will buy everything"},
            ]
        }
    )
    verify_quotes(data, "We are a global firm focused on advisory.")
    flags = [i["quote_verified"] for i in data["stated_priorities"]]
    assert flags == [True, False]


def test_render_handles_sloppy_and_empty_data():
    md = render_markdown({"strategy_summary": "Focus on advisory.", "constraints": "Capital rules"})
    assert "Focus on advisory." in md and "Capital rules" in md
    assert "Not a recommendation" in md


def test_condense_keeps_relevant_lines_within_cap():
    from deal_fit.edgar import condense

    filler = "\n".join(f"Boilerplate sentence number {i} about nothing." for i in range(200))
    section = "Heading\n" + filler + "\nWe plan to acquire technology capabilities.\n" + filler
    out = condense(section, 600)
    assert len(out) <= 700
    assert "acquire technology capabilities" in out
    assert condense("short", 600) == "short"


def test_quotes_hidden_by_default_but_shown_with_evidence():
    data = verify_quotes(
        normalize({"stated_priorities": [{"priority": "Grow", "quote": "we will grow"}]}),
        "we will grow fast",
    )
    assert "we will grow" not in render_markdown(data)
    assert '"we will grow"' in render_markdown(data, evidence=True)


def test_unverified_quote_flagged_even_when_hidden():
    data = verify_quotes(
        normalize({"stated_priorities": [{"priority": "X", "quote": "made up"}]}), "other"
    )
    assert "quote not found in filing" in render_markdown(data)


def test_render_marks_unverified_quote():
    data = verify_quotes(
        normalize({"stated_priorities": [{"priority": "X", "quote": "not in source"}]}), "other"
    )
    assert "quote not found in filing" in render_markdown(data)
