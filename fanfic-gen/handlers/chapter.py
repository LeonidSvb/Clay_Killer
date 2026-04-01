import html
import json
import re
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from states import ChapterStates
from logic.storage import get_current_story, save_story
from logic.generate import generate_chapter, generate_technique_options
from logic.summarize import summarize_chapter
from logic.state import add_chapter, apply_summary

router = Router()

TECHNIQUES_PATH = Path("techniques.json")

INTENTS = [
    ("pacing_slow",   "Замедлить / атмосфера"),
    ("pacing_fast",   "Экшен / динамика"),
    ("character",     "Углубить персонажа"),
    ("plot",          "Повернуть сюжет"),
    ("world",         "Раскрыть мир"),
    ("relationships", "Отношения"),
]


def load_techniques_by_category(category: str) -> list:
    with open(TECHNIQUES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [t for t in data["techniques"] if t["category"] == category]


def format_chapter(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def split_text(text: str, chunk_size: int = 3500) -> list:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        pos = text.rfind("\n\n", 0, chunk_size)
        if pos == -1:
            pos = text.rfind("\n", 0, chunk_size)
        if pos == -1:
            pos = text.rfind(". ", 0, chunk_size)
        if pos == -1:
            pos = chunk_size
        chunks.append(text[:pos].strip())
        text = text[pos:].strip()
    return chunks


def get_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Продолжить так же", callback_data="dir:continue"),
            InlineKeyboardButton(text="Написать своё",     callback_data="dir:custom"),
        ],
        [
            InlineKeyboardButton(text=label, callback_data=f"intent:{key}")
            for key, label in INTENTS[:3]
        ],
        [
            InlineKeyboardButton(text=label, callback_data=f"intent:{key}")
            for key, label in INTENTS[3:]
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_chapter(message: Message, state: FSMContext, story: dict, chapter_text: str) -> None:
    chapter_num = story["state"].get("chapter_count", 1)
    chunks = split_text(format_chapter(chapter_text))

    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            await message.answer(
                chunk + f"\n\n<i>Глава {chapter_num} — {story['title']}</i>",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML",
            )
        else:
            await message.answer(chunk, parse_mode="HTML")

    await state.set_state(ChapterStates.waiting_direction)


async def generate_and_send(
    message: Message,
    state: FSMContext,
    user_id: int,
    story: dict,
    direction: str | None,
) -> None:
    wait_msg = await message.answer("Генерирую главу...")
    try:
        chapter_text = await generate_chapter(story, direction)
        story = add_chapter(story, chapter_text)
        try:
            summary = await summarize_chapter(story, chapter_text)
            story = apply_summary(story, summary)
        except Exception:
            pass
        save_story(user_id, story)
        await wait_msg.delete()
        await send_chapter(message, state, story, chapter_text)
    except Exception as e:
        await wait_msg.edit_text(
            f"Ошибка при генерации: {e}\n\nПопробуй /next ещё раз или /regen"
        )


# --- /next ---

@router.message(Command("next"))
async def cmd_next(message: Message, state: FSMContext):
    user_id = message.from_user.id
    story = get_current_story(user_id)
    if not story:
        await message.answer("Нет активной истории. Создай новую через /start")
        return
    direction = story.get("direction")
    story["direction"] = None
    save_story(user_id, story)
    await state.clear()
    await generate_and_send(message, state, user_id, story, direction)


# --- Tier 1: базовые кнопки ---

@router.callback_query(F.data == "dir:continue")
async def cb_continue(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    user_id = callback.from_user.id
    story = get_current_story(user_id)
    if not story:
        return
    await state.clear()
    await generate_and_send(callback.message, state, user_id, story, None)


@router.callback_query(F.data == "dir:custom")
async def cb_custom(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(ChapterStates.waiting_custom)
    await callback.message.answer("Напиши куда должна пойти история:")


@router.message(ChapterStates.waiting_custom)
async def handle_custom_direction(message: Message, state: FSMContext):
    direction = message.text
    await state.clear()
    user_id = message.from_user.id
    story = get_current_story(user_id)
    if not story:
        await message.answer("Нет активной истории.")
        return
    await generate_and_send(message, state, user_id, story, direction)


# --- Tier 1: intent кнопки → запускают Tier 2 ---

@router.callback_query(F.data.startswith("intent:"))
async def cb_intent(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    category = callback.data.split(":")[1]
    user_id = callback.from_user.id
    story = get_current_story(user_id)
    if not story:
        return

    techniques = load_techniques_by_category(category)
    if not techniques:
        await callback.message.answer("Техники для этой категории не найдены.")
        return

    wait_msg = await callback.message.answer("Подбираю варианты под твою историю...")
    try:
        options = await generate_technique_options(story, category, techniques)
        await state.update_data(technique_options=options)
        await state.set_state(ChapterStates.waiting_technique_choice)

        rows = []
        for i, opt in enumerate(options):
            rows.append([
                InlineKeyboardButton(
                    text=opt["title"],
                    callback_data=f"tech:{i}"
                )
            ])
        rows.append([
            InlineKeyboardButton(text="Написать своё", callback_data="dir:custom_from_tech")
        ])

        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await wait_msg.delete()
        await callback.message.answer(
            "<b>Выбери как пойдёт следующая глава:</b>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        await wait_msg.edit_text(f"Ошибка: {e}")


# --- Tier 2: выбор конкретной техники ---

@router.callback_query(F.data.startswith("tech:"))
async def cb_pick_technique(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    options = data.get("technique_options", [])

    if idx >= len(options):
        await callback.message.answer("Что-то пошло не так. Попробуй /next")
        return

    direction = options[idx]["direction"]
    await callback.message.edit_reply_markup(reply_markup=None)

    user_id = callback.from_user.id
    story = get_current_story(user_id)
    if not story:
        return

    await state.clear()
    await generate_and_send(callback.message, state, user_id, story, direction)


@router.callback_query(F.data == "dir:custom_from_tech")
async def cb_custom_from_tech(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(ChapterStates.waiting_custom)
    await callback.message.answer("Напиши куда должна пойти история:")
