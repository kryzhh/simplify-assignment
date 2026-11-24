"""Local operator commands; credentials and scheduler controls stay out of HTTP."""
import argparse
import json
import os

from .runtime import configured_store
from .sips import Plans


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="python -m gold")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("issue-token", "trace"):
        commands.add_parser(name).add_argument("user")
    commands.add_parser("tick")
    commands.add_parser("serve")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("gold.api:create_app", factory=True, host=os.getenv("GOLD_HOST", "127.0.0.1"),
                    port=int(os.getenv("GOLD_PORT", "8000")), limit_concurrency=64,
                    proxy_headers=False, access_log=False)
        return

    store = configured_store()
    store.initialize()
    if args.command == "issue-token":
        print(store.issue_token(args.user))
    elif args.command == "tick":
        print(Plans(store).run_due())
    else:
        after = 0
        while events := store.trace(args.user, after):
            for event in events:
                print(json.dumps(event, ensure_ascii=False))
            after = events[-1]["seq"]


if __name__ == "__main__":
    main()
