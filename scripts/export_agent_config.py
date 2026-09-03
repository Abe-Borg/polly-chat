#!/usr/bin/env python3
"""Export the DigitalOcean agent's configuration into the repository.

Half of this system is the code in this repo; the other half is the agent's
configuration, which lives in DigitalOcean's control panel. That half cannot be
reviewed, diffed, or rolled back while it is only in a web UI. This script
copies it into `deploy/agent-config.json` so both halves can be read together
and a change to the agent shows up in `git diff` like any other change.

Usage (from the repository root):

    python scripts/export_agent_config.py

It needs a DigitalOcean **personal access token**, which is NOT the same thing
as the agent key in `.env`:

  * `DO_API_KEY`          — the agent's own key. Talks to the agent. Cannot
                            read configuration.
  * `DO_MANAGEMENT_TOKEN` — a personal access token from the DigitalOcean
                            control panel (API -> Tokens). Reads configuration.
                            Read scope is enough.

Put the second one in `.env` next to the others, or export it in the shell.
`DIGITALOCEAN_ACCESS_TOKEN` is also accepted, since that is the name the
`doctl` CLI uses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

API_ROOT = "https://api.digitalocean.com/v2/gen-ai/agents"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "deploy" / "agent-config.json"

# Substrings that mark a field as secret. Matched against the lowercased key
# name, so this catches api_key, access_key, secret_key, anthropic_api_key and
# anything else shaped like a credential without needing to enumerate them.
SECRET_HINTS = ("key", "secret", "token", "password", "credential")

# Fields that change on their own and would otherwise fill every diff with
# noise, hiding the configuration change you actually want to see.
VOLATILE_FIELDS = ("updated_at", "last_indexing_job", "usage", "metrics")

# The settings that decide how the agent behaves. Printed as a summary so the
# export is readable without opening the JSON.
KEY_SETTINGS = (
    "name",
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "k",
    "retrieval_method",
    "provide_citations",
    "region",
)


def redact(value, key_name: str = ""):
    """Recursively replace anything credential-shaped with a placeholder.

    The output file is committed, so it must never carry a secret. Values are
    replaced by their length alone, which is enough to tell "this is set" from
    "this is empty" without revealing the value.
    """
    lowered = key_name.lower()
    if any(hint in lowered for hint in SECRET_HINTS) and isinstance(value, str):
        return f"<redacted: {len(value)} chars>" if value else "<empty>"

    if isinstance(value, dict):
        return {
            k: redact(v, k)
            for k, v in sorted(value.items())
            if k not in VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [redact(item, key_name) for item in value]
    return value


def request_json(client: httpx.Client, url: str) -> dict:
    """GET a URL, turning the common failures into advice instead of a stack trace."""
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        sys.exit(f"Could not reach the DigitalOcean API: {type(exc).__name__}: {exc}")

    if response.status_code == 401:
        sys.exit(
            "DigitalOcean rejected the token (401).\n"
            "DO_MANAGEMENT_TOKEN must be a personal access token from the control\n"
            "panel (API -> Tokens), not the agent key from DO_API_KEY."
        )
    if response.status_code == 404:
        sys.exit(f"Not found (404): {url}\nCheck the agent UUID.")
    if response.status_code != 200:
        sys.exit(f"DigitalOcean returned HTTP {response.status_code}: {response.text[:500]}")

    return response.json()


def find_agent_uuid(client: httpx.Client, agent_url: str) -> str:
    """Pick the agent to export, preferring the one this app actually calls."""
    payload = request_json(client, API_ROOT)
    agents = payload.get("agents") or []

    if not agents:
        sys.exit("The token is valid, but this account has no agents.")

    # The deployment URL in DO matches DO_AGENT_URL in .env, so the agent this
    # app talks to can be identified without asking.
    if agent_url:
        wanted = agent_url.strip().rstrip("/")
        for agent in agents:
            deployed = (agent.get("deployment") or {}).get("url") or ""
            if deployed.strip().rstrip("/") == wanted:
                print(f"Matched DO_AGENT_URL to agent '{agent.get('name')}'.")
                return agent["uuid"]
        print(f"No agent's deployment URL matches DO_AGENT_URL ({wanted}).", file=sys.stderr)

    if len(agents) == 1:
        only = agents[0]
        print(f"Using the account's only agent, '{only.get('name')}'.")
        return only["uuid"]

    print("\nSeveral agents found. Re-run with --agent-uuid <uuid>:\n", file=sys.stderr)
    width = max(len(a["uuid"]) for a in agents)
    for agent in agents:
        deployed = (agent.get("deployment") or {}).get("url") or "(not deployed)"
        print(f"  {agent['uuid']:<{width}}  {agent.get('name', '?'):<30} {deployed}", file=sys.stderr)
    sys.exit(1)


def summarize(agent: dict) -> None:
    """Print the settings that govern behaviour, so the export is self-explaining."""
    print("\nAgent settings")
    print("-" * 60)
    for field in KEY_SETTINGS:
        value = agent.get(field)
        if isinstance(value, dict):
            value = value.get("name") or value.get("uuid")
        if value is not None:
            print(f"  {field:<20} {value}")

    for label, field in (("knowledge bases", "knowledge_bases"),
                         ("functions", "functions"),
                         ("guardrails", "guardrails"),
                         ("child agents", "child_agents")):
        items = agent.get(field) or []
        names = [i.get("name", "?") for i in items if isinstance(i, dict)]
        print(f"  {label:<20} {len(items)}" + (f"  ({', '.join(names)})" if names else ""))

    instruction = agent.get("instruction") or ""
    print(f"\nInstruction ({len(instruction)} chars) — the agent's persona:")
    print("-" * 60)
    if instruction:
        preview = instruction if len(instruction) <= 600 else instruction[:600] + "\n  [...]"
        print("\n".join(f"  {line}" for line in preview.splitlines()))
    else:
        print("  (empty — the agent has no persona configured)")
    print("-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--agent-uuid", help="Export this agent instead of auto-detecting.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Where to write the config (default: {DEFAULT_OUTPUT}).")
    args = parser.parse_args()

    load_dotenv()
    token = (
        os.getenv("DO_MANAGEMENT_TOKEN")
        or os.getenv("DIGITALOCEAN_ACCESS_TOKEN")
        or ""
    ).strip()

    if not token:
        sys.exit(
            "No management token found.\n\n"
            "Create one at https://cloud.digitalocean.com/account/api/tokens\n"
            "(read scope is enough), then add it to .env as:\n\n"
            "    DO_MANAGEMENT_TOKEN=dop_v1_...\n\n"
            "This is separate from DO_API_KEY, which only talks to the agent."
        )

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=httpx.Timeout(30.0, connect=15.0)) as client:
        uuid = args.agent_uuid or find_agent_uuid(client, os.getenv("DO_AGENT_URL") or "")
        agent = request_json(client, f"{API_ROOT}/{uuid}").get("agent") or {}

    if not agent:
        sys.exit("The API returned no agent object. Check the UUID and try again.")

    summarize(agent)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline keep the file diff-stable, so a real
    # configuration change stands out instead of drowning in reordered fields.
    args.output.write_text(
        json.dumps(redact(agent), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    rel = args.output.relative_to(REPO_ROOT) if args.output.is_relative_to(REPO_ROOT) else args.output
    print(f"\nWrote {rel} (secrets redacted).")
    print("Commit it, and from now on `git diff` shows agent changes too.")


if __name__ == "__main__":
    main()
