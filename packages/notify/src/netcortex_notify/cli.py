import argparse
import json

from .service import _check_news, check_news


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline-safe notification fixture CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    news = sub.add_parser("news")
    news.add_argument("provider", nargs="?")
    news.add_argument("target", nargs="?")
    news.add_argument("--mock", action="store_true", required=True)
    live_news = sub.add_parser("live-news")
    live_news.add_argument("provider", nargs="?")
    live_news.add_argument("target", nargs="?")
    args = parser.parse_args()
    if args.command == "news":
        print(json.dumps(_check_news(args.provider, args.target, api_key=None), indent=2))
    else:
        print(check_news(args.provider, args.target).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
