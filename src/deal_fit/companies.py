"""Company choices for the search dropdown: SEC's full list, with a built-in fallback."""

from __future__ import annotations

import re

# Large US public companies, used if SEC's list cannot be loaded. Financial
# services first, since that is the main audience.
FALLBACK = [
    ("GS", "Goldman Sachs Group, Inc."), ("JPM", "JPMorgan Chase & Co."),
    ("MS", "Morgan Stanley"), ("BAC", "Bank of America Corp"), ("C", "Citigroup Inc."),
    ("WFC", "Wells Fargo & Company"), ("SCHW", "Charles Schwab Corp"),
    ("BLK", "BlackRock, Inc."), ("BX", "Blackstone Inc."), ("KKR", "KKR & Co. Inc."),
    ("APO", "Apollo Global Management, Inc."), ("AXP", "American Express Company"),
    ("V", "Visa Inc."), ("MA", "Mastercard Incorporated"), ("PYPL", "PayPal Holdings, Inc."),
    ("COF", "Capital One Financial Corp"), ("USB", "U.S. Bancorp"), ("PNC", "PNC Financial Services Group"),
    ("TFC", "Truist Financial Corp"), ("BK", "Bank of New York Mellon Corp"),
    ("STT", "State Street Corp"), ("TROW", "T. Rowe Price Group, Inc."),
    ("BEN", "Franklin Resources, Inc."), ("IVZ", "Invesco Ltd."), ("AMP", "Ameriprise Financial, Inc."),
    ("LPLA", "LPL Financial Holdings Inc."), ("RJF", "Raymond James Financial, Inc."),
    ("NDAQ", "Nasdaq, Inc."), ("ICE", "Intercontinental Exchange, Inc."), ("CME", "CME Group Inc."),
    ("SPGI", "S&P Global Inc."), ("MCO", "Moody's Corporation"), ("MSCI", "MSCI Inc."),
    ("AIG", "American International Group, Inc."), ("MET", "MetLife, Inc."),
    ("PRU", "Prudential Financial, Inc."), ("TRV", "Travelers Companies, Inc."),
    ("CB", "Chubb Limited"), ("ALL", "Allstate Corporation"), ("MMC", "Marsh & McLennan Companies"),
    ("AON", "Aon plc"), ("BRK-B", "Berkshire Hathaway Inc."),
    ("MSFT", "Microsoft Corporation"), ("AAPL", "Apple Inc."), ("GOOGL", "Alphabet Inc."),
    ("AMZN", "Amazon.com, Inc."), ("META", "Meta Platforms, Inc."), ("NVDA", "NVIDIA Corporation"),
    ("ORCL", "Oracle Corporation"), ("CRM", "Salesforce, Inc."), ("IBM", "International Business Machines"),
    ("ADBE", "Adobe Inc."), ("INTC", "Intel Corporation"), ("CSCO", "Cisco Systems, Inc."),
    ("WMT", "Walmart Inc."), ("COST", "Costco Wholesale Corporation"), ("TGT", "Target Corporation"),
    ("HD", "Home Depot, Inc."), ("KO", "Coca-Cola Company"), ("PEP", "PepsiCo, Inc."),
    ("PG", "Procter & Gamble Company"), ("JNJ", "Johnson & Johnson"), ("PFE", "Pfizer Inc."),
    ("UNH", "UnitedHealth Group Incorporated"), ("CVS", "CVS Health Corporation"),
    ("XOM", "Exxon Mobil Corporation"), ("CVX", "Chevron Corporation"), ("GE", "GE Aerospace"),
    ("BA", "Boeing Company"), ("F", "Ford Motor Company"), ("GM", "General Motors Company"),
    ("DIS", "Walt Disney Company"), ("NFLX", "Netflix, Inc."), ("T", "AT&T Inc."), ("VZ", "Verizon Communications Inc."),
]

_SMALL = {"inc", "corp", "co", "llc", "ltd", "plc", "lp", "the", "of", "and", "de", "nv", "sa"}
# Words SEC lists in capitals that should stay capitals.
_KEEP_UPPER = {"IBM", "AT&T", "CVS", "KKR", "AIG", "PNC", "ETF", "USA", "US", "UK", "ADR", "REIT", "BDC", "CME", "ICE", "S&P", "TD", "HSBC", "UBS", "GE", "3M", "AMC", "MSCI"}


_SPECIAL = {
    "JPMORGAN": "JPMorgan", "BLACKROCK": "BlackRock", "PAYPAL": "PayPal",
    "NVIDIA": "NVIDIA", "MASTERCARD": "Mastercard", "CITIGROUP": "Citigroup",
}


def pretty_name(raw: str) -> str:
    """'GOLDMAN SACHS GROUP INC' -> 'Goldman Sachs Group Inc'; leave mixed-case names alone."""
    raw = re.sub(r"\s*/[A-Za-z]{2,3}/?\s*$", "", raw).strip()  # SEC's "/DE/" state tags
    if raw != raw.upper():
        return raw
    words = []
    for i, w in enumerate(raw.split()):
        bare = w.strip(",.")
        if bare in _SPECIAL:
            words.append(w.replace(bare, _SPECIAL[bare]))
        elif bare in _KEEP_UPPER:
            words.append(w)
        elif bare.lower() in _SMALL and i > 0:
            words.append(w.capitalize() if bare.lower() in {"inc", "corp", "co", "llc", "ltd", "plc", "lp"} else w.lower())
        else:
            words.append(w.capitalize())
    return " ".join(words)


def label(ticker: str, name: str) -> str:
    return f"{pretty_name(name)}  ({ticker.upper()})"


def options_from_sec(rows: list[dict]) -> dict[str, str]:
    """Map dropdown label -> ticker, keeping SEC's order (largest companies first)."""
    out: dict[str, str] = {}
    for row in rows:
        ticker, name = str(row.get("ticker", "")).strip(), str(row.get("title", "")).strip()
        if ticker and name:
            out.setdefault(label(ticker, name), ticker)
    return out


def fallback_options() -> dict[str, str]:
    return {label(t, n): t for t, n in FALLBACK}


class CompanyIndex:
    """Type-ahead search over company labels with predictable, executive-friendly ranking.

    Ranking, best first: exact ticker, ticker starts with the text, name starts with
    it, any word in the name starts with it, then anywhere in the name. Ties keep
    SEC's order, which lists the largest companies first.
    """

    SUGGESTED = ["GS", "JPM", "MS", "BAC", "C", "BLK", "BX", "MSFT"]

    def __init__(self, options: dict[str, str]):
        self.options = options
        self._rows = []
        for i, (lab, ticker) in enumerate(options.items()):
            name = re.sub(r"\s*\([^()]*\)\s*$", "", lab).lower()
            self._rows.append((i, lab, ticker.lower(), name))

    @staticmethod
    def _score(token: str, ticker: str, name: str) -> int | None:
        if ticker == token:
            return 0
        if ticker.startswith(token):
            return 1
        if name.startswith(token):
            return 2
        if any(w.startswith(token) for w in re.split(r"[^a-z0-9&]+", name)):
            return 3
        if token in name:
            return 4
        return None

    def search(self, query: str, limit: int = 8) -> list[str]:
        tokens = query.lower().split()
        if not tokens:
            return self.suggestions()
        hits = []
        for i, lab, ticker, name in self._rows:
            scores = [self._score(t, ticker, name) for t in tokens]
            if None not in scores:
                hits.append((max(scores), i, lab))
        hits.sort()
        return [lab for _, _, lab in hits[:limit]]

    def suggestions(self) -> list[str]:
        """Shown when the box is opened empty: well-known financial names that exist in the list."""
        by_ticker = {t.lower(): lab for lab, t in self.options.items()}
        picks = [by_ticker[t.lower()] for t in self.SUGGESTED if t.lower() in by_ticker]
        return picks or list(self.options)[:8]


def ticker_from_label(choice: str | None) -> str:
    """Pull the ticker out of a dropdown label such as 'Goldman Sachs Group Inc  (GS)'."""
    m = re.search(r"\(([^()]+)\)\s*$", choice or "")
    return m.group(1) if m else (choice or "").strip()
