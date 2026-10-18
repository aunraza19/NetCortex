import argparse
import json

from netcortex_core import ModuleUnavailable, Settings

from .service import fixture_search, ingest, search_runbook


def main() -> None:
    parser = argparse.ArgumentParser(description="RouterOS runbook indexing and search")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="offline cited fixture lookup")
    fixture.add_argument("query")
    fixture.add_argument("--mock", action="store_true", required=True)
    fixture.add_argument("-k", type=int, default=3)
    search = commands.add_parser("search", help="live pgvector search via shared core Settings")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=5)
    commands.add_parser(
        "ingest", help="fetch approved official pages and index using shared core Settings"
    )
    args = parser.parse_args()
    if args.command == "fixture":
        output = fixture_search(args.query, args.k)
    elif args.command == "search":
        output = [item.model_dump() for item in search_runbook(args.query, args.k)]
    else:
        settings = Settings()
        if settings.database_url is None:
            raise ModuleUnavailable("runbook ingest unavailable: database URL is not configured")
        output = {
            "indexed_chunks": ingest(
                database_url=settings.database_url.get_secret_value(),
                ollama_base_url=settings.ollama_base_url,
                embed_model=settings.embed_model,
            )
        }
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
