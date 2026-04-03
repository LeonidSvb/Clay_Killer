import json
from os.path import basename
from pathlib import Path

_STATE_PATH = Path(__file__).parent.parent / "ui_state.json"


def _load() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(state: dict) -> None:
    _STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_key(source_file: str, workspace_id=None) -> str:
    if source_file.startswith("[DB]"):
        return f"db:{workspace_id}"
    if source_file.startswith("[PV]"):
        name = source_file.removeprefix("[PV]").strip()
        return f"pv:{name}"
    return f"csv:{basename(source_file)}"


def load_source(key: str) -> dict:
    return _load().get("sources", {}).get(key, {})


def save_source(key: str, data: dict) -> None:
    state = _load()
    existing = state.setdefault("sources", {}).get(key, {})
    existing.update(data)
    state["sources"][key] = existing
    state["last_source_key"] = key
    _save(state)
