"""Paid integration evaluation; run explicitly, never as part of default pytest."""

import argparse
import json
import os
from pathlib import Path

from email_cli.provider_paths import save_private
from email_cli.read_screening import ReadScreener
from email_cli.screening_policy import MODEL, POLICY_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--split", choices=["calibration", "holdout", "all"], default="all")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    key = (
        args.key_file.expanduser().read_text().strip()
        if args.key_file
        else os.environ.get("TYPESAFE_API_KEY", "")
    )
    if not key:
        parser.error("Set TYPESAFE_API_KEY or pass --key-file (never a literal key).")
    if not 1 <= args.repeat <= 5:
        parser.error("--repeat must be between 1 and 5")
    cases = json.loads(
        (Path(__file__).parents[1] / "tests/fixtures/screening_cases.json").read_text()
    )
    screener = ReadScreener(key)
    results = []
    for repeat in range(args.repeat):
        for case in cases:
            if args.split != "all" and case.get("split", "calibration") != args.split:
                continue
            parts = []
            for field, mime in (("text", "text/plain"), ("html", "text/html")):
                if field in case:
                    parts.append({"mime_type": mime, "content": case[field]})
            state = {
                "subject": case.get("subject", ""),
                "parts": parts,
                "attachments": case.get("attachments", []),
                "incomplete": False,
            }
            decision = screener.evaluate(state)
            row = {
                "id": case["id"],
                "split": case.get("split", "calibration"),
                "repeat": repeat,
                "expected": case["expected"],
                **decision.as_dict(),
            }
            results.append(row)
            print(json.dumps(row), flush=True)
            save_private(
                args.output, {"model": MODEL, "policy_version": POLICY_VERSION, "results": results}
            )
    false_approvals = [
        r for r in results if r["expected"] == "flagged" and r["decision"] == "auto_approved"
    ]
    false_flags = [
        r for r in results if r["expected"] == "auto_approved" and r["decision"] == "flagged"
    ]
    api_errors = [
        r
        for r in results
        if any(x.startswith(("jev_", "unexpected_model", "invalid_")) for x in r["reasons"])
    ]
    summary = {
        "cases": len(results),
        "false_approvals": len(false_approvals),
        "false_flags": len(false_flags),
        "api_errors": len(api_errors),
        "input_tokens": sum(r["usage"].get("input_tokens", 0) for r in results),
    }
    save_private(
        args.output,
        {"model": MODEL, "policy_version": POLICY_VERSION, "summary": summary, "results": results},
    )
    print(json.dumps(summary))
    raise SystemExit(1 if false_approvals or api_errors else 0)


if __name__ == "__main__":
    main()
