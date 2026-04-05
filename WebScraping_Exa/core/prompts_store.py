"""
core/prompts_store.py — single source of truth for all prompts.

Reads/writes prompts.json in project root.
Structure:
  {
    "system_context": "...",
    "exa_query": "...",
    "prompts": {
      "name": {
        "prompt": "...",
        "output_type": "Text|Boolean|Score|Structured",
        "output_config": {}
      }
    }
  }
"""

import json
from pathlib import Path

PROMPTS_JSON = Path(__file__).parent.parent / "prompts.json"

_DEFAULTS: dict = {
    "system_context": "Always respond with valid JSON only. No markdown, no explanation.",
    "exa_query": "",
    "prompts": {},
    "fc_schemas": {},
}


def load() -> dict:
    if not PROMPTS_JSON.exists():
        return {k: v for k, v in _DEFAULTS.items()}
    try:
        data = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
        for k, v in _DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return {k: v for k, v in _DEFAULTS.items()}


def save(data: dict) -> None:
    PROMPTS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Convenience helpers ────────────────────────────────────────────────────────

def get_system_context() -> str:
    return load().get("system_context", _DEFAULTS["system_context"])


def get_exa_query() -> str:
    return load().get("exa_query", "")


def set_exa_query(text: str) -> None:
    data = load()
    data["exa_query"] = text
    save(data)


def list_prompts() -> list[str]:
    return sorted(load().get("prompts", {}).keys())


def get_prompt(name: str) -> dict:
    return load()["prompts"][name]


def set_prompt(name: str, prompt: str, output_type: str = "Text", output_config: dict | None = None) -> None:
    data = load()
    data["prompts"][name] = {
        "prompt": prompt,
        "output_type": output_type or "Text",
        "output_config": output_config or {},
    }
    save(data)


def rename_prompt(old_name: str, new_name: str) -> None:
    data = load()
    if old_name in data["prompts"]:
        data["prompts"][new_name] = data["prompts"].pop(old_name)
        save(data)


def delete_prompt(name: str) -> bool:
    data = load()
    if name in data["prompts"]:
        del data["prompts"][name]
        save(data)
        return True
    return False


# ── Firecrawl schema store ─────────────────────────────────────────────────────

def list_fc_schemas() -> list[str]:
    return sorted(load().get("fc_schemas", {}).keys())


def get_fc_schema(name: str) -> dict:
    """Returns {"prompt": str, "schema": dict}."""
    return load().get("fc_schemas", {}).get(name, {})


def set_fc_schema(name: str, prompt: str, schema: dict) -> None:
    data = load()
    data.setdefault("fc_schemas", {})[name] = {"prompt": prompt, "schema": schema}
    save(data)


def delete_fc_schema(name: str) -> bool:
    data = load()
    if name in data.get("fc_schemas", {}):
        del data["fc_schemas"][name]
        save(data)
        return True
    return False
