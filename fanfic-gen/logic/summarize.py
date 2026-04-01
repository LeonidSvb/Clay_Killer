import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL", "deepseek/deepseek-chat")
API_URL = "https://openrouter.ai/api/v1/chat/completions"


async def summarize_chapter(story: dict, chapter_text: str) -> dict:
    state = story["state"]
    chapter_num = state.get("chapter_count", 1)
    existing_chars = json.dumps(state.get("characters", []), ensure_ascii=False, indent=2)

    prompt = (
        f"Проанализируй главу {chapter_num} новеллы и верни JSON.\n\n"
        f"Существующие персонажи:\n{existing_chars}\n\n"
        f"Текст главы:\n{chapter_text}\n\n"
        f"Верни ТОЛЬКО валидный JSON без markdown блоков:\n"
        "{\n"
        f'  "chapter": {chapter_num},\n'
        '  "summary": "3-6 предложений: ключевые события, что произошло, важные детали",\n'
        '  "key_events": ["событие 1"],\n'
        '  "character_changes": ["изменение персонажа если есть"],\n'
        '  "important_details": ["важная деталь"],\n'
        '  "characters": [\n'
        '    {\n'
        '      "name": "имя",\n'
        '      "traits": "черты характера",\n'
        '      "goal": "текущая цель",\n'
        '      "current_state": "состояние и местонахождение",\n'
        '      "relationships": "отношения с другими"\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "Включи всех существующих персонажей + новых из этой главы. Обнови поля если изменились."
    )

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    last_exc = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(2):
            try:
                r = await client.post(API_URL, headers=headers, json=payload)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"].strip()

                if content.startswith("```"):
                    parts = content.split("```")
                    content = parts[1]
                    if content.startswith("json"):
                        content = content[4:]

                return json.loads(content.strip())
            except Exception as e:
                last_exc = e

    raise last_exc
