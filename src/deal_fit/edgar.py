"""Fetch a company's latest 10-K from SEC EDGAR and pull out the sections we need.

SEC requires every automated request to identify the requester. Set the
SEC_USER_AGENT environment variable to "Your Name your.email@example.com".
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

import requests
from bs4 import BeautifulSoup

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# Per-section caps keep the prompt a reasonable size. Sections longer than the
# cap are condensed to their most relevant paragraphs, not cut off at the end.
SECTION_CAPS = {"business": 160_000, "risk_factors": 60_000, "mdna": 80_000}

RELEVANCE = re.compile(
    r"acqui|divest|merger|joint venture|collaborat|partnership|strateg|invest(?:ing|ment)? in"
    r"|capabilit|technolog|artificial intelligence|\bAI\b|digital|platform|expand|growth"
    r"|priorit|initiative|transform|exit|sale of|approval|restrict|synerg|integrat",
    re.I,
)


class EdgarError(RuntimeError):
    pass


@dataclass
class Filing:
    company: str
    ticker: str
    form: str
    filed: str
    period: str
    url: str
    accession: str = ""

    @property
    def label(self) -> str:
        """Short year label such as FY2025, taken from the period-end date."""
        return f"FY{self.period[:4]}" if self.period else "FY?"


def _headers() -> dict:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise EdgarError(
            'SEC requires you to identify yourself. Set SEC_USER_AGENT to your name and '
            'email, e.g. $env:SEC_USER_AGENT="Jane Doe jane@example.com"'
        )
    return {"User-Agent": ua}


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers=_headers(), timeout=60)
    if resp.status_code == 403:
        raise EdgarError(
            "SEC refused the request (403). Check that SEC_USER_AGENT is a real "
            "name and email, and avoid sending many requests quickly."
        )
    resp.raise_for_status()
    return resp


@lru_cache(maxsize=1)
def _company_list() -> list[dict]:
    """SEC's ticker list, downloaded once per process."""
    return list(_get(TICKERS_URL).json().values())


def company_list() -> list[dict]:
    """All SEC-registered companies with tickers: [{'ticker', 'title', 'cik_str'}, ...]."""
    return _company_list()


def resolve_company(query: str) -> tuple[int, str, str]:
    """Return (cik, name, ticker) for a ticker or company-name query."""
    q = query.strip().lower()
    companies = _company_list()
    exact = [c for c in companies if c["ticker"].lower() == q]
    if exact:
        c = exact[0]
        return int(c["cik_str"]), c["title"], c["ticker"]
    words = q.split()
    matches = [c for c in companies if all(w in c["title"].lower() for w in words)]
    if not matches:
        raise EdgarError(f"No SEC-registered company found for {query!r}. Try the ticker.")
    c = min(matches, key=lambda m: len(m["title"]))
    return int(c["cik_str"]), c["title"], c["ticker"]


def list_10ks(cik: int, name: str, ticker: str, count: int = 1) -> list[Filing]:
    """The most recent `count` annual reports (10-K), newest first."""
    submissions = _get(SUBMISSIONS_URL.format(cik=cik)).json()["filings"]
    # "recent" only covers about the last 1,000 filings, which for a heavy filer
    # (banks file thousands of bond documents) can be just a few months. Older
    # filings live in separate files listed under "files".
    blocks = [submissions["recent"]]
    older = iter(submissions.get("files", []))
    filings: list[Filing] = []
    while True:
        for block in blocks:
            for i, form in enumerate(block["form"]):
                if form != "10-K":
                    continue
                acc = block["accessionNumber"][i].replace("-", "")
                url = ARCHIVE_URL.format(cik=cik, acc=acc, doc=block["primaryDocument"][i])
                filings.append(
                    Filing(name, ticker, form, block["filingDate"][i], block["reportDate"][i], url, acc)
                )
        if len(filings) >= count:
            break
        extra = next(older, None)
        if extra is None:
            break
        blocks = [_get(SUBMISSIONS_FILE_URL.format(name=extra["name"])).json()]
    if not filings:
        raise EdgarError(f"No 10-K found for {name}.")
    filings.sort(key=lambda f: f.filed, reverse=True)
    return filings[:count]


def latest_10k(cik: int, name: str, ticker: str) -> Filing:
    return list_10ks(cik, name, ticker, 1)[0]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "ix:header"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def download_filing_text(filing: Filing) -> str:
    return html_to_text(_get(filing.url).text)


def _item(n: str) -> re.Pattern:
    return re.compile(rf"(?im)^\s*item\s+{n}\s*[\.\:\-–—]")


def extract_section(text: str, start: str, ends: list[str]) -> str:
    """Longest span from an 'Item <start>' heading to the next 'Item' in `ends`.

    Taking the longest span skips the table of contents, which also contains
    the headings but with almost no text between them.
    """
    end_pats = [_item(e) for e in ends]
    best = ""
    for m in _item(start).finditer(text):
        stops = [p.search(text, m.end()) for p in end_pats]
        stop = min((s.start() for s in stops if s), default=len(text))
        if stop - m.start() > len(best):
            best = text[m.start():stop]
    return best


def condense(section: str, cap: int) -> str:
    """Shrink a section to `cap` characters by keeping its most relevant lines.

    Lines are scored by how many deal/strategy keywords they contain; the best
    ones are kept in their original order. The opening lines are always kept.
    """
    if len(section) <= cap:
        return section
    lines = section.split("\n")
    scored = sorted(
        range(len(lines)),
        key=lambda i: (-len(RELEVANCE.findall(lines[i])), i),
    )
    keep, used = set(range(min(10, len(lines)))), 0
    used = sum(len(lines[i]) + 1 for i in keep)
    for i in scored:
        if i in keep or not RELEVANCE.search(lines[i]):
            continue
        if used + len(lines[i]) + 1 > cap:
            continue
        keep.add(i)
        used += len(lines[i]) + 1
    return "\n".join(lines[i] for i in sorted(keep))


def extract_sections(text: str) -> dict[str, str]:
    """Pull Business, Risk Factors and MD&A, condensed to SECTION_CAPS."""
    raw = {
        "business": extract_section(text, "1", ["1a", "1b", "2"]),
        "risk_factors": extract_section(text, "1a", ["1b", "1c", "2"]),
        "mdna": extract_section(text, "7", ["7a", "8"]),
    }
    return {k: condense(v, SECTION_CAPS[k]) for k, v in raw.items() if len(v) > 2_000}
