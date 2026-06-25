import argparse
import json
import logging
import sys

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
    sub.add_parser("stats", help="Show mailbox storage and email counts")

    p_age = sub.add_parser("list-age", help="List emails oldest-first using state file")
    p_age.add_argument("--cursor", type=int, default=0, help="Cursor position (default: 0)")

    p_sender = sub.add_parser("list-senders", help="List emails grouped by sender")
    p_sender.add_argument("--page-token", default=None, help="Page token for next page")

    p_recipient = sub.add_parser("list-recipients", help="List emails grouped by recipient")
    p_recipient.add_argument("--page-token", default=None, help="Page token for next page")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    try:
        tools = create_tools(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "initialize":
        result = tools.initialize(reset=args.reset)
        print(json.dumps(result, indent=2))

    elif args.command == "stats":
        result = tools.get_mailbox_stats()
        print(json.dumps(result.model_dump(), indent=2))

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


if __name__ == "__main__":
    main()
