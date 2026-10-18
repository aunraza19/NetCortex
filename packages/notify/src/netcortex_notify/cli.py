import argparse
import json

from .service import _check_news, _speak, check_news, speak


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline-safe notification fixture CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    voice = sub.add_parser("speak")
    voice.add_argument("text")
    voice.add_argument("--lang", choices=["en", "ur"], default="en")
    voice.add_argument("--mock", action="store_true", required=True)
    news = sub.add_parser("news")
    news.add_argument("provider", nargs="?")
    news.add_argument("target", nargs="?")
    news.add_argument("--mock", action="store_true", required=True)
    live_voice = sub.add_parser("live-speak")
    live_voice.add_argument("text")
    live_voice.add_argument("--lang", choices=["en", "ur"], default="en")
    live_news = sub.add_parser("live-news")
    live_news.add_argument("provider", nargs="?")
    live_news.add_argument("target", nargs="?")
    args = parser.parse_args()
    if args.command == "speak":
        data = _speak(args.text, args.lang, api_key=None, voice_id=None)
        print(json.dumps({"available": bool(data), "fixture": True, "bytes": len(data)}))
    elif args.command == "news":
        print(json.dumps(_check_news(args.provider, args.target, api_key=None), indent=2))
    elif args.command == "live-speak":
        data = speak(args.text, args.lang)
        print(json.dumps({"available": bool(data), "bytes": len(data)}))
    else:
        print(check_news(args.provider, args.target).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
