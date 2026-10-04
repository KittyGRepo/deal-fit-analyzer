"""Command line entry point.

  deal-fit profile GS                      # fetch latest 10-K from SEC EDGAR
  deal-fit profile --file filings/gs.txt   # use a filing you saved yourself
  deal-fit trajectory GS --years 3         # what changed, and said vs. did
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .edgar import (
    download_filing_text,
    extract_sections,
    latest_10k,
    list_10ks,
    resolve_company,
)
from .pipeline import profile_for
from .profile import DEFAULT_MODEL, build_profile
from .trajectory import build_trajectory


def _load(args) -> tuple[dict[str, str], dict]:
    if args.file:
        text = args.file.read_text(encoding="utf-8")
        filing = {"form": "filing (supplied file)", "period": "?", "filed": "?"}
    else:
        cik, name, ticker = resolve_company(args.company)
        print(f"Using {name} ({ticker})", file=sys.stderr)
        f = latest_10k(cik, name, ticker)
        print(f"Downloading {f.form} filed {f.filed}...", file=sys.stderr)
        text = download_filing_text(f)
        filing = {"form": f.form, "period": f.period, "filed": f.filed, "url": f.url}
    if args.save_text:
        args.save_text.write_text(text, encoding="utf-8")
    sections = extract_sections(text)
    if not sections:
        # Fall back to the start of the document if headings could not be found.
        print("Warning: could not find 10-K sections; using the start of the text.", file=sys.stderr)
        sections = {"business": text[:200_000]}
    print(
        "Sections: " + ", ".join(f"{k} ({len(v):,} chars)" for k, v in sections.items()),
        file=sys.stderr,
    )
    return sections, filing


def _trajectory(args) -> str:
    cik, name, ticker = resolve_company(args.company)
    print(f"Using {name} ({ticker})", file=sys.stderr)
    filings = list_10ks(cik, name, ticker, args.years)[::-1]  # oldest first
    if len(filings) < 2:
        raise ValueError(f"Found only {len(filings)} 10-K for {name}; need at least 2.")
    profiles = [profile_for(f, model=args.model, refresh=args.refresh) for f in filings]
    print("Comparing years...", file=sys.stderr)
    result = build_trajectory(profiles, model=args.model)
    return result.to_json() if args.json else result.to_markdown(evidence=args.evidence)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deal-fit", description="Acquirer profile from public filings.")
    sub = p.add_subparsers(dest="cmd", required=True)
    prof = sub.add_parser("profile", help="Build an acquirer profile and target criteria")
    prof.add_argument("company", nargs="?", help="Ticker or company name (fetches latest 10-K)")
    prof.add_argument("--file", type=Path, help="Use a saved filing text file instead of SEC")
    prof.add_argument("--save-text", type=Path, help="Save the downloaded filing text here")
    prof.add_argument("-o", "--output", type=Path, help="Write the profile here (default: print)")
    prof.add_argument("--evidence", action="store_true", help="Show the supporting quote for each item")
    prof.add_argument("--json", action="store_true", help="Output raw JSON instead of Markdown")
    prof.add_argument("--model", default=DEFAULT_MODEL)

    traj = sub.add_parser(
        "trajectory",
        help="Compare several years: what changed, and what the company said vs. did",
    )
    traj.add_argument("company", help="Ticker or company name")
    traj.add_argument("--years", type=int, default=3, help="How many recent 10-Ks (2-5, default 3)")
    traj.add_argument("-o", "--output", type=Path, help="Write the result here (default: print)")
    traj.add_argument("--evidence", action="store_true", help="Show the supporting quote for each item")
    traj.add_argument("--json", action="store_true", help="Output raw JSON instead of Markdown")
    traj.add_argument("--refresh", action="store_true", help="Ignore saved profiles and rebuild")
    traj.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args(argv)

    if args.cmd == "profile" and not args.company and not args.file:
        p.error("give a company ticker/name or --file")
    if args.cmd == "trajectory" and not 2 <= args.years <= 5:
        p.error("--years must be between 2 and 5")
    try:
        if args.cmd == "trajectory":
            out = _trajectory(args)
        else:
            sections, filing = _load(args)
            profile = build_profile(sections, filing, model=args.model)
            out = profile.to_json() if args.json else profile.to_markdown(evidence=args.evidence)
    except Exception as exc:  # friendly message instead of a stack trace
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(out, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
