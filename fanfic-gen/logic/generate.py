import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL", "deepseek/deepseek-chat")
API_URL = "https://openrouter.ai/api/v1/chat/completions"


async def _call(messages: list, max_tokens: int = 3000, temperature: float = 0.8) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        last_exc = None
        for attempt in range(2):
            try:
                r = await client.post(API_URL, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_exc = e
        raise last_exc


def _build_context(story: dict) -> str:
    state = story["state"]
    parts = []

    parts.append(f"Жанр и стиль: {state['genre']}")
    parts.append(f"Главный герой: {state['hero']}")
    parts.append(f"Мир и сеттинг: {state['world']}")
    parts.append(f"Начальная ситуация: {state['start_situation']}")

    chars = state.get("characters", [])
    if chars:
        lines = ["Текущие персонажи:"]
        for c in chars:
            lines.append(
                f"- {c['name']}: характер — {c.get('traits', '')}, "
                f"цель — {c.get('goal', '')}, "
                f"состояние — {c.get('current_state', '')}, "
                f"отношения — {c.get('relationships', '')}"
            )
        parts.append("\n".join(lines))

    summaries = story.get("summaries", [])
    if summaries:
        lines = ["Краткое содержание предыдущих глав:"]
        for s in summaries[-10:]:
            lines.append(f"Глава {s['chapter']}: {s['summary']}")
        parts.append("\n".join(lines))

    last_chapters = story.get("last_chapters", [])
    if last_chapters:
        parts.append(
            "Последние главы (полный текст):\n\n"
            + "\n\n---\n\n".join(last_chapters[-2:])
        )

    return "\n\n".join(parts)


async def generate_chapter(story: dict, direction: str = None) -> str:
    state = story["state"]
    chapter_num = state.get("chapter_count", 0) + 1
    context = _build_context(story)

    system = (
        f"Ты пишешь художественную новеллу.\n"
        f"Стиль и жанр: {state['genre']}\n"
        f"Язык: русский (если не указано иное)\n\n"
        f"Правила:\n"
        f"- строго соблюдай continuity сюжета и логику событий\n"
        f"- помни всех персонажей и их характеры\n"
        f"- не меняй характер персонажа без внутренней причины\n"
        f"- следуй предыдущим событиям из summaries\n"
        f"- пиши художественно, с деталями, диалогами и атмосферой\n"
        f"- объём главы: 1200-1500 слов"
    )

    user_msg = (
        context
        + f"\n\nНапиши главу {chapter_num}.\n"
        f"Начни строго с заголовка: Глава {chapter_num}: [название главы]"
    )

    if direction and direction != "continue":
        user_msg += f"\n\nНаправление для этой главы: {direction}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    return await _call(messages, max_tokens=3000, temperature=0.8)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


INTENT_LABELS = {
    "pacing_slow": "замедлить темп, добавить атмосферы и глубины",
    "pacing_fast": "добавить динамики и напряжения",
    "character": "углубить характер или внутренний мир персонажа",
    "plot": "сделать неожиданный поворот в сюжете",
    "world": "раскрыть мир и его устройство",
    "relationships": "развить отношения между персонажами",
}


async def generate_technique_options(story: dict, category: str, techniques: list) -> list:
    state = story["state"]
    summaries = story.get("summaries", [])
    last_summary = summaries[-1]["summary"] if summaries else "история только началась"
    chars = state.get("characters", [])

    chars_text = ""
    if chars:
        lines = []
        for c in chars:
            lines.append(f"- {c['name']}: {c.get('traits', '')}. Цель: {c.get('goal', '')}. Состояние: {c.get('current_state', '')}")
        chars_text = "\n".join(lines)
    else:
        chars_text = "персонажи ещё не установлены"

    techniques_text = ""
    for t in techniques:
        req = ", ".join(t.get("requires", [])) or "нет"
        techniques_text += (
            f"ID: {t['id']}\n"
            f"Название: {t['name']}\n"
            f"Описание: {t['description']}\n"
            f"Подсказка: {t['prompt_hint']}\n"
            f"Частота: {t['frequency']} | Требует: {req}\n\n"
        )

    intent_label = INTENT_LABELS.get(category, "улучшить следующую главу")

    prompt = (
        f"Ты помогаешь управлять нарративом новеллы.\n\n"
        f"Текущий контекст:\n"
        f"Жанр: {state['genre']}\n"
        f"Глава: {state.get('chapter_count', 1)}\n"
        f"Персонажи:\n{chars_text}\n"
        f"Последние события: {last_summary}\n\n"
        f"Пользователь хочет: {intent_label}\n\n"
        f"Доступные техники:\n{techniques_text}"
        f"Выбери 4-5 наиболее релевантных техник для ЭТОГО момента истории.\n"
        f"Учитывай: какие персонажи уже есть, что произошло, частоту использования.\n"
        f"Для каждой выбранной техники:\n"
        f"- адаптируй под конкретных персонажей этой истории\n"
        f"- напиши title: название приёма + конкретно что произойдёт (до 10 слов, с именами персонажей)\n"
        f"- напиши direction: 3-5 предложений — как именно будет построена глава, что случится, какой эффект на сюжет\n\n"
        f"Верни ТОЛЬКО валидный JSON без markdown блоков:\n"
        f'{{ "options": [ {{"title": "...", "direction": "..."}} ] }}'
    )

    result = await _call([{"role": "user", "content": prompt}], max_tokens=1000, temperature=0.85)
    data = _parse_json(result)
    return data["options"]


async def generate_options(story: dict) -> list:
    state = story["state"]
    summaries = story.get("summaries", [])
    last_summary = summaries[-1]["summary"] if summaries else "история только началась"

    prompt = (
        f"На основе истории предложи 3 варианта развития сюжета для следующей главы.\n\n"
        f"Жанр: {state['genre']}\n"
        f"Последние события: {last_summary}\n\n"
        f"Требования:\n"
        f"- каждый вариант 1-2 предложения\n"
        f"- варианты сильно отличаются друг от друга\n"
        f"- интригующие, соответствуют жанру\n\n"
        f'Верни ТОЛЬКО валидный JSON без markdown блоков:\n'
        f'{{"options": ["вариант 1", "вариант 2", "вариант 3"]}}'
    )

    result = await _call([{"role": "user", "content": prompt}], max_tokens=500, temperature=0.9)
    data = _parse_json(result)
    return data["options"]
