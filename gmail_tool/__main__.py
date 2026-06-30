import argparse
import base64
import json
import logging
import sys
from pathlib import Path

from . import create_tools


def main():
    parser = argparse.ArgumentParser(
        prog="python -m gmail_tool",
        description="Gmail cleanup tool — one-off CLI for experimenting",
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug logs"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("initialize", help="Collect all message IDs oldest-first into state file")
    p_init.add_argument("--reset", action="store_true", help="Discard any existing checkpoint and start over")
    p_stats = sub.add_parser("stats", help="Show mailbox storage and email counts")
    p_stats.add_argument(
        "--bytes", dest="unit", action="store_const", const="bytes", default="mb",
        help="Show sizes in bytes instead of MB"
    )

    p_age = sub.add_parser("list-age", help="List emails oldest-first using state file")
    p_age.add_argument("--cursor", type=int, default=0, help="Cursor position (default: 0)")

    p_sender = sub.add_parser("list-senders", help="List emails grouped by sender")
    p_sender.add_argument("--page-token", default=None, help="Page token for next page")

    p_recipient = sub.add_parser("list-recipients", help="List emails grouped by recipient")
    p_recipient.add_argument("--page-token", default=None, help="Page token for next page")

    p_get = sub.add_parser("get-emails", help="Fetch full content for one or more email IDs")
    p_get.add_argument("ids", nargs="+", help="One or more message IDs")

    p_att = sub.add_parser("get-attachment", help="Download an attachment to a file")
    p_att.add_argument("--message-id", required=True, help="Message ID containing the attachment")
    p_att.add_argument("--attachment-id", required=True, help="Attachment ID (from get-emails output)")
    p_att.add_argument("--output", required=True, help="Path to save the attachment")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Suppress noisy Google API client library warnings
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

    try:
        tools = create_tools(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "initialize":
        result = tools.initialize(reset=args.reset)
        print(json.dumps(result, indent=2))

    elif args.command == "stats":
        result = tools.get_mailbox_stats(unit=args.unit)
        print(json.dumps(result, indent=2))

    elif args.command == "list-age":
        result = tools.list_emails_by_age(cursor=args.cursor)
        output = {
            "next_cursor": result["next_cursor"],
            "emails": [e.model_dump() for e in result["emails"]],
        }
        print(json.dumps(output, indent=2))

    elif args.command == "list-senders":
        result = tools.list_emails_by_sender(page_token=args.page_token)
        output = {
            "next_page_token": result["next_page_token"],
            "senders": [s.model_dump() for s in result["senders"]],
        }
        print(json.dumps(output, indent=2))

    elif args.command == "list-recipients":
        result = tools.list_emails_by_recipient(page_token=args.page_token)
        output = {
            "next_page_token": result["next_page_token"],
            "recipients": [r.model_dump() for r in result["recipients"]],
        }
        print(json.dumps(output, indent=2))

    elif args.command == "get-emails":
        result = tools.get_emails(email_ids=args.ids)
        output = {
            "emails": [e.model_dump() for e in result["emails"]],
            "failed_ids": result["failed_ids"],
        }
        print(json.dumps(output, indent=2))

    elif args.command == "get-attachment":
        result = tools.get_attachment(
            message_id=args.message_id, attachment_id=args.attachment_id
        )
        output_path = Path(args.output)
        output_path.write_bytes(base64.urlsafe_b64decode(result["data"]))
        print(f"Saved {result['size_bytes']} bytes to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
