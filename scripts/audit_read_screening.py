"""Classify a bounded Gmail sample without releasing bodies or changing sender approvals."""

import argparse
import json
from pathlib import Path

from email_cli.cli import configured_client
from email_cli.parsing import extract_headers
from email_cli.provider_paths import save_private
from email_cli.read_screening import ReadScreener
from email_cli.screening_content import gmail_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_results <= 100:
        parser.error("--max-results must be between 1 and 100")
    client = configured_client(args.account, "gmail")
    screener = ReadScreener(args.key_file.expanduser().read_text().strip())
    listing = client.search_messages(query="in:inbox", max_results=args.max_results)
    results = []
    for item in listing["messages"]:
        # Explicitly invoked screening is authorized to inspect unapproved messages internally.
        # Only metadata and decision scores leave this script; no body is printed or saved.
        message = client._get_message(message_id=item["id"], message_format="full")
        decision = screener.evaluate(gmail_state(message), message_id=item["id"])
        headers = extract_headers(message.get("payload") or {})
        row = {
            "id": item["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "sender_already_approved": client._message_sender_approved(message),
            **decision.as_dict(),
        }
        results.append(row)
        save_private(args.output, {"account": args.account, "results": results})
        print(json.dumps({"processed": len(results), "decision": row["decision"]}), flush=True)
    summary = {
        "account": args.account,
        "count": len(results),
        "auto_approved": sum(r["decision"] == "auto_approved" for r in results),
        "flagged": sum(r["decision"] == "flagged" for r in results),
        "input_tokens": sum(r["usage"].get("input_tokens", 0) for r in results),
    }
    save_private(args.output, {"summary": summary, "results": results})
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
