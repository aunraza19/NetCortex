"""Compare Gemma with thinking on and off on the three hand-made incidents.

    uv run python packages/agent/scripts/compare_thinking.py [--runs 2]

Needs the model server (OLLAMA_BASE_URL). Prints one row per run and a summary per mode.
"""

import argparse
import asyncio
import re
import statistics

from netcortex_agent.agent import run_investigation
from netcortex_agent.cases import Case, all_cases

URDU = re.compile(r"[؀-ۿ]")


def score(case: Case, report) -> dict:
    params_ok = all(report.template_params.get(k) == v for k, v in case.expected_params.items())
    if case.name == "dns_slow" and report.template_id.value == "dns_servers":
        params_ok = "203.0.113.53" not in report.template_params.get("servers", [])
    return {
        "cause": report.likely_cause == case.expected_cause,
        "template": report.template_id == case.expected_template,
        "params": params_ok and report.template_id == case.expected_template,
        "urdu": bool(URDU.search(report.customer_message_ur)),
        "en_words": len(report.customer_message_en.split()),
    }


async def main(runs: int) -> None:
    rows = []
    for thinking in (False, True):
        for case in all_cases():
            for run in range(runs):
                report, stats = await run_investigation(
                    case.site.id, case.detection, case.window, site=case.site, thinking=thinking
                )
                s = score(case, report)
                rows.append((thinking, case.name, stats, s))
                print(
                    f"thinking={'on ' if thinking else 'off'} {case.name:12} run{run + 1} "
                    f"{stats.seconds:6.1f}s cause={'Y' if s['cause'] else 'n'} "
                    f"template={report.template_id.value:15} params={'Y' if s['params'] else 'n'} "
                    f"tools={stats.tool_calls} retries={stats.output_retries} "
                    f"fallback={stats.fell_back} urdu={'Y' if s['urdu'] else 'n'} "
                    f"en_words={s['en_words']}",
                    flush=True,
                )
                print(f"    params={report.template_params} summary={report.summary!r}")
    print()
    for thinking in (False, True):
        mine = [r for r in rows if r[0] == thinking]
        n = len(mine)
        print(
            f"thinking {'on ' if thinking else 'off'}: "
            f"median {statistics.median(r[2].seconds for r in mine):.1f}s, "
            f"cause {sum(r[3]['cause'] for r in mine)}/{n}, "
            f"template {sum(r[3]['template'] for r in mine)}/{n}, "
            f"params {sum(r[3]['params'] for r in mine)}/{n}, "
            f"retries {sum(r[2].output_retries for r in mine)}, "
            f"fallbacks {sum(r[2].fell_back for r in mine)}, "
            f"avg tool calls {statistics.fmean(len(r[2].tool_calls) for r in mine):.1f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2, help="runs per case and mode")
    asyncio.run(main(parser.parse_args().runs))
