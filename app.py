"""Deal Fit Analyzer web page. Run with: streamlit run app.py"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import streamlit as st

from streamlit_searchbox import st_searchbox

from deal_fit.companies import CompanyIndex, fallback_options, options_from_sec, ticker_from_label
from deal_fit.edgar import EdgarError, company_list, list_10ks, resolve_company
from deal_fit.pipeline import profile_for
from deal_fit.trajectory import build_trajectory
from deal_fit.web_render import profile_html, report_document, trajectory_html

CACHE = Path(__file__).parent / "filings" / "cache"
PROFILE, TRAJECTORY = "One-year profile", "Multi-year comparison"

st.set_page_config(
    page_title="Deal Fit Analyzer", page_icon="📈", layout="centered",
    initial_sidebar_state="expanded",
)

PAGE_CSS = """
<style>
.block-container{padding-top:3.6rem;max-width:1020px}
#MainMenu,footer{visibility:hidden}
.df-hero-eyebrow{font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;color:#5B6776;font-weight:700}
.df-hero-title{font-size:2.5rem;font-weight:750;color:#0B2545;letter-spacing:-.02em;line-height:1.1;margin:.2rem 0 .5rem}
.df-hero-sub{font-size:1.08rem;color:#3A4757;max-width:720px;margin-bottom:1.2rem}
.df-field-label{font-size:.82rem;font-weight:600;color:#1B2430;margin:.4rem 0 .2rem}
div[data-testid="stSidebar"]{background:#F3F6FA}
.stButton>button[kind="primary"]{background:#0B2545;border:0;border-radius:8px;font-weight:600;padding:.55rem 1.4rem}
.stButton>button[kind="primary"]:hover{background:#13396B}
</style>
"""


def sec_identity_configured() -> bool:
    """SEC needs the site owner's contact on downloads (env var or Streamlit secret)."""
    if os.environ.get("SEC_USER_AGENT"):
        return True
    try:
        ua = st.secrets.get("SEC_USER_AGENT")
    except Exception:  # no secrets file
        ua = None
    if ua:
        os.environ["SEC_USER_AGENT"] = ua
        return True
    return False


@st.cache_resource(ttl=86400, show_spinner=False)
def _sec_index() -> CompanyIndex:
    return CompanyIndex(options_from_sec(company_list()))  # raises on failure, so not cached


def company_index() -> CompanyIndex:
    """Search over every SEC-registered company, or a built-in list if SEC is unreachable."""
    try:
        return _sec_index()
    except Exception:
        return CompanyIndex(fallback_options())


def run_analysis(ticker: str, mode: str, years: int, api_key: str):
    """Returns (company name, Profile or Trajectory). Raises on any problem."""
    with st.status("Working...", expanded=True) as status:
        try:
            cik, name, symbol = resolve_company(ticker)
            st.write(f"Found {name} ({symbol})")
            if mode == PROFILE:
                filing = list_10ks(cik, name, symbol, 1)[0]
                result = profile_for(filing, CACHE, api_key=api_key, log=st.write)
            else:
                filings = list_10ks(cik, name, symbol, years)[::-1]  # oldest first
                if len(filings) < 2:
                    raise ValueError(f"Found only {len(filings)} annual report for {name}.")
                profiles = [
                    profile_for(f, CACHE, api_key=api_key, log=st.write) for f in filings
                ]
                st.write("Comparing years...")
                result = build_trajectory(profiles, api_key=api_key)
        except Exception:
            status.update(label="Something went wrong", state="error", expanded=False)
            raise
        status.update(label="Done", state="complete", expanded=False)
    return name, result


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic rejected that API key. Check that you copied it completely."
    if isinstance(exc, anthropic.RateLimitError):
        return "Your Anthropic account hit a rate limit. Wait a minute and try again."
    if isinstance(exc, anthropic.APIStatusError):
        return f"The Anthropic API returned an error ({exc.status_code}). Try again shortly."
    if isinstance(exc, (EdgarError, ValueError)):
        return str(exc)
    return f"Something unexpected went wrong: {exc}"


def report_html(saved: dict, evidence: bool) -> str:
    r = saved["result"]
    if saved["mode"] == PROFILE:
        return profile_html(r.data, r.filing, evidence=evidence)
    return trajectory_html(r.data, r.years, evidence=evidence)


# ---- page -----------------------------------------------------------------

st.markdown(PAGE_CSS, unsafe_allow_html=True)
st.markdown(
    '<div class="df-hero-eyebrow">Corporate strategy &amp; M&amp;A intelligence</div>'
    '<div class="df-hero-title">Deal Fit Analyzer</div>'
    '<div class="df-hero-sub">What a company says it wants, what it has actually done, and what '
    "would fit, drawn only from its own SEC annual reports. Use it on a potential buyer "
    "or on a competitor.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Your Anthropic API key")
    api_key = st.text_input("API key", type="password", key="api_key", label_visibility="collapsed")
    st.caption(
        "This tool runs on your own key. It is sent only to Anthropic with your request, "
        "is kept in memory for this session, and is never saved by this app. "
        "[Get a key](https://console.anthropic.com/)"
    )
    st.caption(
        "Cost: roughly \\$0.30-0.50 per year of filings for a company not analyzed before "
        "(about \\$1 for a 3-year comparison). Companies already analyzed are free."
    )

if not sec_identity_configured():
    st.error(
        "This app is not fully set up: the site owner must set SEC_USER_AGENT "
        "(a name and email, which SEC requires on downloads)."
    )
    st.stop()

index = company_index()
st.markdown('<div class="df-field-label">Company</div>', unsafe_allow_html=True)
choice = st_searchbox(
    index.search,
    placeholder="Search by company name or ticker, for example Goldman or GS",
    default_options=index.suggestions(),
    key="company",
    edit_after_submit="option",
)
left, right = st.columns([3, 2])
mode = left.radio("View", [PROFILE, TRAJECTORY], horizontal=True, key="mode")
years = 3
if mode == TRAJECTORY:
    years = right.slider("Years of annual reports", 2, 4, 3, key="years")

if st.button("Analyze", type="primary", key="run"):
    if not api_key.strip():
        st.error("Paste your Anthropic API key in the sidebar first.")
    elif not choice:
        st.error("Choose a company first. Start typing a name or ticker.")
    else:
        try:
            name, result = run_analysis(ticker_from_label(choice), mode, years, api_key.strip())
            st.session_state["result"] = {"name": name, "result": result, "mode": mode}
        except Exception as exc:
            st.session_state.pop("result", None)
            st.error(friendly_error(exc))

saved = st.session_state.get("result")
if saved:
    show_quotes = st.toggle("Show the supporting quote for each item", key="evidence")
    html = report_html(saved, show_quotes)
    slug = "".join(ch for ch in saved["name"].split()[0].lower() if ch.isalnum())
    kind = "profile" if saved["mode"] == PROFILE else "trajectory"
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "Download report (HTML)", report_document(html, f"{saved['name']} - {kind}"),
        file_name=f"{slug}_{kind}.html", mime="text/html", use_container_width=True,
    )
    c2.download_button(
        "Download (Markdown)", saved["result"].to_markdown(evidence=show_quotes),
        file_name=f"{slug}_{kind}.md", use_container_width=True,
    )
    c3.download_button(
        "Download (JSON)", saved["result"].to_json(),
        file_name=f"{slug}_{kind}.json", use_container_width=True,
    )
    st.html(html)

if not saved:  # a result already carries its own disclaimer
    st.caption(
        "Hypotheses for discussion, generated by AI from public SEC filings. It can contain "
        "errors; quotes are checked against the filing and unverified ones are flagged. "
        "Not investment advice, not a prediction, and not affiliated with any company shown."
    )
