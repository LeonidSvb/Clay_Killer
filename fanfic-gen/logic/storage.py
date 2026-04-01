import json
import datetime
import time
from pathlib import Path

DATA_DIR = Path("data")


def _get_file(user_id: int) -> Path:
    return DATA_DIR / f"user_{user_id}.json"


def load_user_data(user_id: int) -> dict:
    f = _get_file(user_id)
    if not f.exists():
        return {"stories": [], "current_story_id": None}
    with open(f, "r", encoding="utf-8") as fp:
        return json.load(fp)


def save_user_data(user_id: int, data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(_get_file(user_id), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def get_current_story(user_id: int) -> dict | None:
    data = load_user_data(user_id)
    cid = data.get("current_story_id")
    if not cid:
        return None
    for s in data["stories"]:
        if s["id"] == cid:
            return s
    return None


def save_story(user_id: int, story: dict) -> None:
    data = load_user_data(user_id)
    for i, s in enumerate(data["stories"]):
        if s["id"] == story["id"]:
            data["stories"][i] = story
            save_user_data(user_id, data)
            return
    data["stories"].append(story)
    if not data.get("current_story_id"):
        data["current_story_id"] = story["id"]
    save_user_data(user_id, data)


def create_story(user_id: int, title: str, state: dict) -> dict:
    data = load_user_data(user_id)
    story_id = f"story_{int(time.time())}"
    story = {
        "id": story_id,
        "title": title,
        "created_at": datetime.datetime.now().isoformat(),
        "state": state,
        "summaries": [],
        "last_chapters": [],
        "all_chapters": [],
        "direction": None,
    }
    data["stories"].append(story)
    data["current_story_id"] = story_id
    save_user_data(user_id, data)
    return story


def set_current_story(user_id: int, story_id: str) -> bool:
    data = load_user_data(user_id)
    for s in data["stories"]:
        if s["id"] == story_id:
            data["current_story_id"] = story_id
            save_user_data(user_id, data)
            return True
    return False


def get_all_stories(user_id: int) -> list:
    return load_user_data(user_id).get("stories", [])


def delete_story(user_id: int, story_id: str) -> bool:
    data = load_user_data(user_id)
    before = len(data["stories"])
    data["stories"] = [s for s in data["stories"] if s["id"] != story_id]
    if len(data["stories"]) == before:
        return False
    if data.get("current_story_id") == story_id:
        data["current_story_id"] = data["stories"][-1]["id"] if data["stories"] else None
    save_user_data(user_id, data)
    return True
