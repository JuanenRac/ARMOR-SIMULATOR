"""Feed the real firmware code of a node with the buses of `buses.py` and compare what it answers with what it must answer.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

    python -m armor_simulator.node_bench --bus ld2450 --driver ./sim_bench            # every fault of the bus, seed 1
    python -m armor_simulator.node_bench --bus pzem --driver ./sim_bench --fault corrupt --fault silent
    python -m armor_simulator.node_bench --bus alarm-loop --record cases.jsonl        # only write the cases
    python -m armor_simulator.node_bench --bus alarm-loop --replay cases.jsonl --driver ./sim_bench
    python -m armor_simulator.node_bench --bus pzem --driver ./sim_bench --report pzem.json        # also keep which fault passed or failed
    python -m armor_simulator.node_bench --merge pzem.json ld2450.json                              # one matrix, bus by fault, from several reports

The driver is a small program that every node keeps in its tests (`tests/sim_bench.cpp`): it is built from the core files of the firmware, reads the cases from its standard
input and prints one answer per case (see `buses.py`). A case passes when the answer is exactly the expected text. The exit status is 0 when every case passes, 1 when one
differs and 2 when the run could not be made. Only simulated data goes through; nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import buses

TIMEOUT_S = 60


def run_driver(driver: list[str], cases: list[buses.Case], timeout: float = TIMEOUT_S) -> dict[str, str]:
    """Plays the cases to the driver and gives its answers by case id."""
    text = "".join(case.line() + "\n" for case in cases)
    done = subprocess.run(driver, input=text, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if done.returncode != 0:
        raise buses.BusError(f"the driver stopped with status {done.returncode}: {done.stderr.strip()[:300]}")
    answers: dict[str, str] = {}
    for line in done.stdout.splitlines():
        identifier, _, answer = line.partition("\t")
        if identifier:
            answers[identifier] = answer
    return answers


def compare(cases: list[buses.Case], answers: dict[str, str]) -> list[dict]:
    report = []
    for case in cases:
        answer = answers.get(case.id)
        report.append({"bus": case.bus, "case": case.id, "fault": case.fault, "passed": answer == case.expect, "expected": case.expect, "answered": answer})
    return report


def coverage(bus: str, seed: int, driver: str, report: list[dict]) -> dict:
    """What a run played, for `--report`: every fault of the bus as passed, failed or not-run (the ones that were not asked for)."""
    played = {row["fault"]: ("passed" if row["passed"] else "failed") for row in report}
    faults = {name: played.get(name, "not-run") for name in buses.FAULTS[bus]}
    return {"bus": bus, "seed": seed, "driver": driver, "faults": faults, "cases": len(report), "failed": sum(1 for row in report if not row["passed"])}


def merge(paths: list[Path]) -> str:
    """The reports of several runs as one matrix (a line per bus, a column per fault); a fault that failed in any run is failed, one played anywhere is not 'not-run'."""
    rows: dict[str, dict[str, str]] = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            bus, faults = data["bus"], data["faults"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise buses.BusError(f"{path} is not a report of the bench ({error})") from None
        if bus not in buses.FAULTS or not isinstance(faults, dict):
            raise buses.BusError(f"{path} is not a report of the bench (bus {bus!r})")
        row = rows.setdefault(bus, {})
        for name, state in faults.items():
            old = row.get(name, "not-run")
            row[name] = "failed" if "failed" in (old, state) else ("passed" if "passed" in (old, state) else "not-run")
    lines = []
    for bus in sorted(rows):
        lines.append(bus + ": " + ", ".join(f"{name}={state}" for name, state in rows[bus].items()))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armor_simulator.node_bench", description=__doc__.split("\n\n")[0])
    parser.add_argument("--bus", choices=buses.BUSES)
    parser.add_argument("--fault", action="append", help="only this fault (repeat for several); default: every fault of the bus")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--driver", help="the program built from the firmware core files (a path; arguments may follow in the same text)")
    parser.add_argument("--record", type=Path, metavar="FILE", help="write the cases to FILE as JSON lines and stop (an existing file is never overwritten)")
    parser.add_argument("--replay", type=Path, metavar="FILE", help="play the cases of a recording instead of generating them")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--report", type=Path, metavar="FILE", help="also write which fault of the bus passed, failed or was not run, as JSON (an existing file is never overwritten)")
    parser.add_argument("--merge", type=Path, nargs="+", metavar="FILE", help="print one matrix (bus by fault) from several reports written with --report, and stop")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.merge:
        try:
            print(merge(args.merge))
        except buses.BusError as error:
            print(f"node bench: {error}", file=sys.stderr)
            return 2
        return 0
    if not args.bus:
        parser.error("--bus is needed (or --merge to join reports)")
    try:
        cases = buses.load(args.replay) if args.replay else buses.cases_for(args.bus, args.seed, tuple(args.fault) if args.fault else None)
        cases = [case for case in cases if case.bus == args.bus]
        if not cases:
            print(f"no case of {args.bus} to play", file=sys.stderr)
            return 2
        if args.record:
            buses.dump(cases, args.record)
            print(f"wrote {len(cases)} cases to {args.record}")
            return 0
        if not args.driver:
            print("--driver is needed (or --record to only write the cases)", file=sys.stderr)
            return 2
        report = compare(cases, run_driver(args.driver.split(), cases))
        if args.report:
            if args.report.exists():
                raise buses.BusError(f"{args.report} exists already; it is never overwritten")
            args.report.write_text(json.dumps(coverage(args.bus, args.seed, args.driver, report), indent=1) + "\n", encoding="utf-8")
    except (buses.BusError, OSError, subprocess.SubprocessError) as error:
        print(f"node bench: {error}", file=sys.stderr)
        return 2
    failed = [row for row in report if not row["passed"]]
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for row in report:
            print(f"{'PASS' if row['passed'] else 'FAIL'} {row['case']}")
            if not row["passed"]:
                print(f"  expected: {row['expected'][:400]}\n  answered: {str(row['answered'])[:400]}")
    print(f"NODE_BENCH={'FAIL' if failed else 'PASS'} bus={args.bus} cases={len(report)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
