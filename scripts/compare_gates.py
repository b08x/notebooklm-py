#!/usr/bin/env python
"""Compare the Jev check-worthiness gate with the rule-based gate (fact-59).

Samples N stored, SFL-tagged chunks from the local Postgres, runs both gates,
and prints the agreement rate, Cohen's kappa and a confusion matrix. Each Jev
call is a paid OpenRouter request (``OPENROUTER_API_KEY``).

    uv run python scripts/compare_gates.py --n 100
"""

from __future__ import annotations

import argparse
import asyncio
import json

from notebooklm._app.factcheck_runs import run_gate_comparison
from notebooklm.db.session import async_session_maker


async def _main(n: int, as_json: bool) -> None:
    async with async_session_maker() as session:
        report = await run_gate_comparison(session, n)
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print(
        f"sampled {report['sampled']} chunks, compared {report['n']} ({report['jev_errors']} Jev errors)"
    )
    print(f"agreement {report['agreement']:.1%}   kappa {report['kappa']:.3f}")
    print()
    print(f"{'':14}{'jev=check':>12}{'jev=skip':>12}")
    for rule in ("check", "skip"):
        row = [report["confusion"][f"rule={rule}/jev={jev}"] for jev in ("check", "skip")]
        print(f"{'rule=' + rule:14}{row[0]:>12}{row[1]:>12}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=50, help="chunks to sample (default 50)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    asyncio.run(_main(args.n, args.json))


if __name__ == "__main__":
    main()
