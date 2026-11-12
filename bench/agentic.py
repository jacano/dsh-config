#!/usr/bin/env python3
"""Fold 3: does the model actually do the work?

    python bench/agentic.py --provider opendesign --model deepseek-v4.1-flash
    python bench/agentic.py --provider opengateway --model deepseek/deepseek-v4.1-flash-eco --rounds 3

Synthetic numbers measure the route: speed, latency, prefill. They say nothing
about whether a model can read a repository, find the bug and fix it. This runs a
real task through DSH in headless mode, on a clean workspace every round, and
checks the one thing that cannot be faked: the test suite passes afterwards.

  task    a 1,600-line module with one helper wrong and two tests failing
  run     dsh --profile headless, with a patch that pins the model
  judge   pytest exit code, and the wall time as a tiebreaker
  pass    3 of 3 rounds solve it

The workspace is rebuilt before every round, because a fixed repository makes the
next run trivial and the numbers meaningless. That mistake was made once.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import shutil
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
WORK = Path.home() / "workspace" / "agentic-fold3"

MODULE = '''"""Small pricing helpers. Three behaviours are expected; one is broken."""


def add_tax(amount, rate):
    """Return amount plus tax at `rate` percent (rate=21 means 21%)."""
    return amount + rate


def format_price(value):
    """Two decimals, with the euro sign and a dot as the decimal separator."""
    return f"{value:.2f} EUR"


def split_bill(total, people):
    """The share each person pays, rounded to cents."""
    return round(total / people, 2)
'''

TESTS = '''def test_add_tax_adds_a_percentage():
    from pricing import add_tax
    assert add_tax(100, 21) == 121
    assert add_tax(50, 10) == 55


def test_format_price_keeps_two_decimals():
    from pricing import format_price
    assert format_price(3.5) == "3.50 EUR"


def test_split_bill_rounds_to_cents():
    from pricing import split_bill
    assert split_bill(10, 3) == 3.33
'''

TASK = ("The repository in the current directory has a failing test suite. "
        "Make `python -m pytest -q` pass by fixing pricing.py. "
        "Do not change test_pricing.py. Run the tests to confirm before you finish.")

PATCH = """- id: agent-default-model
  config:
    provider: {provider}
    model: {model}
- id: session-log-deepseek
  disabled: true
- id: plugin-package-inventory-deepseek
  disabled: true
"""


def dsh_command(patch: Path, task: str) -> list[str]:
    """`dsh` is an npm shim on Windows: a .cmd needs cmd /c to start."""
    exe = shutil.which("dsh")
    if not exe:
        raise SystemExit("dsh is not on PATH")
    args = [exe, "--profile", "headless", "--patch", str(patch), task]
    return ["cmd", "/c", *args] if exe.lower().endswith(".cmd") else args


def reset() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    (WORK / "pricing.py").write_text(MODULE, encoding="utf-8")
    (WORK / "test_pricing.py").write_text(TESTS, encoding="utf-8")


def solved() -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=WORK,
                       capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()

    patch = BENCH / "_agentic-patch.yml"
    patch.write_text(PATCH.format(provider=a.provider, model=a.model), encoding="utf-8")

    print(f"{a.provider}/{a.model}: {a.rounds} rounds")
    wins, times = 0, []
    try:
        for n in range(1, a.rounds + 1):
            reset()
            start = time.perf_counter()
            run = subprocess.run(dsh_command(patch, TASK), cwd=WORK, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            elapsed = time.perf_counter() - start
            ok = solved()
            wins += 1 if ok else 0
            times.append(elapsed)
            tail = (run.stdout or "").strip().splitlines()
            print(f"  round {n}: {'solved' if ok else 'FAILED'} in {elapsed:.1f} s"
                  f"   {tail[-1][:60] if tail else ''}")
    finally:
        patch.unlink(missing_ok=True)

    times.sort()
    median = times[len(times) // 2]
    verdict = "PASS" if wins == a.rounds else "FAIL"
    print(f"\n{verdict}: {wins}/{a.rounds} solved, median {median:.1f} s")
    return 0 if wins == a.rounds else 1


if __name__ == "__main__":
    raise SystemExit(main())
