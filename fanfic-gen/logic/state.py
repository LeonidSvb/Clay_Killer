def apply_summary(story: dict, summary_result: dict) -> dict:
    entry = {
        "chapter": summary_result["chapter"],
        "summary": summary_result["summary"],
        "key_events": summary_result.get("key_events", []),
        "character_changes": summary_result.get("character_changes", []),
        "important_details": summary_result.get("important_details", []),
    }
    story["summaries"].append(entry)

    if len(story["summaries"]) > 10:
        story["summaries"] = story["summaries"][-10:]

    if summary_result.get("characters"):
        story["state"]["characters"] = summary_result["characters"]

    return story


def add_chapter(story: dict, chapter_text: str) -> dict:
    story["last_chapters"].append(chapter_text)
    if len(story["last_chapters"]) > 3:
        story["last_chapters"] = story["last_chapters"][-3:]
    if "all_chapters" not in story:
        story["all_chapters"] = []
    story["all_chapters"].append(chapter_text)
    story["state"]["chapter_count"] = story["state"].get("chapter_count", 0) + 1
    return story


def rollback_chapter(story: dict) -> dict:
    if story["last_chapters"]:
        story["last_chapters"].pop()
    if story.get("all_chapters"):
        story["all_chapters"].pop()
    if story["summaries"]:
        story["summaries"].pop()
    count = story["state"].get("chapter_count", 0)
    if count > 0:
        story["state"]["chapter_count"] = count - 1
    story["direction"] = None
    return story
