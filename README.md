# Deal Fit Analyzer

> **Independent project. Not affiliated with, endorsed by, or sponsored by any company analyzed. Not investment advice. Built only from public SEC filings.**

Reads a company's annual reports (10-Ks) from SEC EDGAR and shows **what it says it wants, what it has actually done, and what kind of acquisition would fit**. Use it on a potential buyer or on a competitor.

> **Hypotheses, not recommendations.** The tool never names new potential targets or tells anyone to buy or sell anything. Gap and criteria sections are labeled as inference. AI summaries can contain errors; always check the source.

## The problem

Corporate development and strategy teams spend a lot of time working out what a buyer actually wants before looking at a single target. The answer is usually spread across hundreds of pages of public filings, and the stated strategy often differs from the deals a company actually does. This tool turns that into a starting thesis in about a minute, and shows its evidence.

## What it produces

**One-year profile** (`deal-fit profile GS`)

- Stated priorities and where it says it is investing, grounded in the filing
- Constraints (for example regulatory approvals and capital rules)
- Deals and other actions the filing describes (acquisitions, sales, partnerships, portfolio reductions)
- Possible capability gaps, clearly labeled as inference with a confidence level
- Suggested target criteria, each tied to the priority or constraint it comes from
- Open questions for a deal team

**Multi-year view** (`deal-fit trajectory GS --years 3`) answers two questions a single filing cannot:

1. **What changed year over year?** Which priorities are new, dropped, strengthened, softened, or shifted, in chronological order.
2. **Said vs. did.** For each stated priority, do the filings describe real actions that back it up? Each gets a verdict: followed through, partly followed through, no matching action found, or went the other way.

It then restates the target criteria in light of what the company *actually* does. Every cited quote must be one of the verified quotes from the cited year's profile.

## Two ways to use it

- **As a buyer:** what does a potential acquirer want, and what kinds of deals fit it?
- **As a competitive-intelligence tool:** point it at a competitor. What is their strategy really, where does their behavior differ from their messaging, and what kind of move might come next?

Both use public filings only.

## Web page

```bash
pip install -e ".[web]"
export SEC_USER_AGENT="Your Name your.email@example.com"
streamlit run app.py
```

Search for a company by name or ticker (matching companies appear as you type, ranked so names that start with what you typed come first), choose a one-year profile or a multi-year comparison, and click Analyze. The result is an executive report: a bottom-line callout, a chronological timeline of what changed, and a said-vs-did scorecard grouped by outcome. It downloads as a one-page HTML report that prints cleanly to PDF.

Each visitor pastes their **own Anthropic API key** in the sidebar, so the site owner pays nothing. The key is sent only to Anthropic with that visitor's request, is held in memory for the session, and is never saved or written to a log. Results can also be downloaded as Markdown or JSON.

To host it for free on Streamlit Community Cloud, point it at `app.py` and add `SEC_USER_AGENT` as a secret (SEC requires a contact on automated downloads; it is never shown to visitors).

## Command line

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=your-key
export SEC_USER_AGENT="Your Name your.email@example.com"   # SEC requires this
deal-fit profile GS
deal-fit trajectory GS --years 3
```

PowerShell: `$env:ANTHROPIC_API_KEY="your-key"` and `$env:SEC_USER_AGENT="Your Name you@example.com"`.

Downloaded filings and per-year profiles are cached in `filings/cache`, so re-runs are fast and free.

Options: `-o file` to save, `--evidence` to show the supporting quote for every item, `--json` for raw structured output, `--file filing.txt` to use a filing you saved yourself, `--model` to choose a model.

## Design choices

- **Grounded in the filing.** The model sees only the company's own 10-K text, with no outside knowledge.
- **Evidence you can check.** Each stated fact carries a verbatim quote. Every quote is checked against the source, and any that is not word-for-word is flagged on the page, even when quotes are hidden.
- **Fact vs. inference.** What the company says and what we infer are shown in separate sections.
- **Verdicts cannot claim more than they know.** "No matching action found" is worded so it never asserts that nothing happened, and a priority with a goal and a means is only "followed through" if the goal itself is evidenced.
- **Smart condensing.** A 10-K can be over a million characters. Long sections are condensed to their most deal-relevant paragraphs rather than cut off at the end.
- **Guaranteed structure.** Output comes through a strict tool schema, and rendering tolerates minor shape errors and repairs stray characters.
- **Written for executives.** One-page reports, one sentence per bullet, most important first.

## Testing against real filings

I checked the output against the actual 10-Ks of large public companies, reading the results critically. That surfaced real problems, all now fixed:

1. **Truncation hid deals.** Long sections were cut off at the end, so the first version missed two real acquisitions. Fixed by condensing to the most deal-relevant paragraphs.
2. **Too few filings for heavy filers.** SEC's "recent filings" list only reaches back a few months for companies that file thousands of bond documents, so only one 10-K was found. Fixed by reading the older filing files too.
3. **A false "no action" verdict.** The comparison said a stated priority (shrinking a legacy investment portfolio) had no visible action, but the filings show it fell from $29.7B to $9.4B. Profiles captured deals but not other actions like portfolio reductions. Fixed by capturing both, and by rewording the verdict.
4. **An overclaiming verdict.** A priority with a goal (reach profitability) and a means (narrow the business) was rated "followed through, high confidence" because the means happened. Fixed by instructing the model to judge the goal itself and to split compound priorities.
5. **A shortened quote.** The model once dropped two words while copying a quote, and the quote checker flagged it. The prompt now says to copy exactly or leave the quote blank; the checker stays on as the safety net.
6. **A corrupted character.** The model once emitted a broken character in "$2-3 billion". Output is now cleaned before display.

**Known limitation:** figures that appear only in financial tables, not in prose, are often missed, so the tool tends to under-claim ("partly followed through") rather than over-claim. For example, it does not report that the portfolio above fell below its target. Extracting key table figures is on the roadmap.

## Roadmap

- [x] Multi-year comparison: year-over-year changes and said vs. did
- [x] Web page with company search and executive report layout
- [ ] Extract key figures from financial tables so verdicts can cite numbers
- [ ] Add 8-K deal announcements to the "did" side
- [ ] Compare two companies side by side (competitive view)
- [ ] Score candidate companies you supply against the criteria
- [ ] Find candidates from public sources, with a source link required for every one
- [ ] Benchmark deal terms against similar past deals in SEC filings

## Data and licensing

Uses only public SEC filings. SEC asks automated users to identify themselves, hence `SEC_USER_AGENT`. Not affiliated with any company analyzed. Nothing it produces is investment advice.

## Tests

```bash
pytest
```

## License

MIT
