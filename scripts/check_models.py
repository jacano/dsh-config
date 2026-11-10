#!/usr/bin/env python3
"""Enforce models-policy.yml against dsh/cordis.patch.yml.

Stdlib only, line-based: the two files are flat enough that a YAML dependency
would cost more than it buys, and this has to run on a fresh checkout.

Checks:
  1. every model row in the patch file is admitted;
  2. every admitted model is in the patch file (no drift either way);
  3. no row is listed as excluded;
  4. the default model is configured and admitted, on the right route;
  5. no model id appears twice.

Exit code 0 when the patch file matches the policy, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCH = ROOT / "dsh" / "cordis.patch.yml"
POLICY = ROOT / "models-policy.yml"

MODEL_ROW = re.compile(r"^(?P<indent>\s+)- id:\s*(?P<id>\S+)\s*$")
TOP_ROW = re.compile(r"^- id:\s*(?P<id>\S+)\s*$")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def patch_models(lines: list[str]) -> list[str]:
    """Model ids under the llm-pi-ai entry, in order."""
    start = None
    for i, line in enumerate(lines):
        if TOP_ROW.match(line) and TOP_ROW.match(line).group("id") == "llm-pi-ai":
            start = i
            break
    if start is None:
        raise SystemExit("FAIL: no llm-pi-ai entry in dsh/cordis.patch.yml")

    models: list[str] = []
    for line in lines[start + 1 :]:
        if TOP_ROW.match(line):
            break
        row = MODEL_ROW.match(line)
        if row and len(row.group("indent")) >= 8:
            models.append(row.group("id"))
    return models


def patch_default(lines: list[str]) -> tuple[str, str]:
    """(provider, model) from the agent-default-model entry."""
    start = None
    for i, line in enumerate(lines):
        if TOP_ROW.match(line) and TOP_ROW.match(line).group("id") == "agent-default-model":
            start = i
            break
    if start is None:
        raise SystemExit("FAIL: no agent-default-model entry")

    provider = model = ""
    for line in lines[start + 1 :]:
        if TOP_ROW.match(line):
            break
        m = re.match(r"^\s+provider:\s*(\S+)", line)
        if m:
            provider = m.group(1)
        m = re.match(r"^\s+model:\s*(\S+)", line)
        if m:
            model = m.group(1)
    if not provider or not model:
        raise SystemExit("FAIL: agent-default-model has no provider/model pair")
    return provider, model


def policy_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if re.match(r"^[a-z_]+:\s*$", line):
            current = line.split(":")[0]
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        row = re.match(r"^\s+- id:\s*(\S+)\s*$", line)
        if row:
            sections[current].append(row.group(1))
    return sections


def admitted_routes(lines: list[str]) -> dict[str, str]:
    """id -> route for the admitted section."""
    routes: dict[str, str] = {}
    current_id = None
    for line in lines:
        row = re.match(r"^\s+- id:\s*(\S+)\s*$", line)
        if row:
            current_id = row.group(1)
            continue
        route = re.match(r"^\s+route:\s*(\S+)\s*$", line)
        if route and current_id:
            routes[current_id] = route.group(1)
    return routes


def main() -> int:
    patch_lines = read_lines(PATCH)
    policy_lines = read_lines(POLICY)

    configured = patch_models(patch_lines)
    sections = policy_sections(policy_lines)
    admitted = sections.get("admitted", [])
    excluded = sections.get("excluded", [])
    routes = admitted_routes(policy_lines)

    problems: list[str] = []

    if not configured:
        problems.append("the patch file serves no models")
    if len(configured) != len(set(configured)):
        dupes = sorted({m for m in configured if configured.count(m) > 1})
        problems.append(f"duplicate model rows: {', '.join(dupes)}")

    for model in configured:
        if model in excluded:
            problems.append(f"{model} is configured but listed as excluded")
        elif model not in admitted:
            problems.append(f"{model} is configured but not admitted (add it to models-policy.yml)")

    for model in admitted:
        if model not in configured:
            problems.append(f"{model} is admitted but missing from the patch file")

    provider, default_model = patch_default(patch_lines)
    if default_model not in admitted:
        problems.append(f"default model {default_model} is not admitted")
    elif default_model not in configured:
        problems.append(f"default model {default_model} is not configured")
    elif routes.get(default_model) and routes[default_model] != provider:
        problems.append(
            f"default model {default_model} is admitted on route "
            f"{routes[default_model]} but the default points at {provider}"
        )

    if problems:
        print("FAIL: dsh/cordis.patch.yml does not match models-policy.yml\n")
        for problem in problems:
            print(f"  - {problem}")
        print("\nFix the patch file, or update the policy with a measurement that justifies it.")
        return 1

    print(f"OK: {len(configured)} model rows, all admitted; default is {provider}/{default_model}")
    for model in configured:
        print(f"  - {model}")
    print(f"\nPolicy holds the line at {len(excluded)} excluded rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
