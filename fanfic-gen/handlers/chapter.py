import html
import re

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
from logic.generate import generate_chapter, generate_options
from logic.summarize import summarize_chapter
from logic.state import add_chapter, apply_summary

router = Router()


def format_chapter(text: str) -> str:
    escaped = html.escape(text)
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return formatted


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


def get_direction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Продолжить так же", callback_data="dir:continue"),
                InlineKeyboardButton(text="Варианты от AI", callback_data="dir:ai"),
            ],
            [
                InlineKeyboardButton(text="Написать своё", callback_data="dir:custom"),
            ],
        ]
    )


async def send_chapter(message: Message, state: FSMContext, story: dict, chapter_text: str) -> None:
    chapter_num = story["state"].get("chapter_count", 1)
    chunks = split_text(format_chapter(chapter_text))

    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            await message.answer(
                chunk + f"\n\n<i>Глава {chapter_num} из {story['title']}</i>",
                reply_markup=get_direction_keyboard(),
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


@router.callback_query(F.data == "dir:ai")
async def cb_ai_options(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    user_id = callback.from_user.id
    story = get_current_story(user_id)
    if not story:
        return

    wait_msg = await callback.message.answer("Генерирую варианты...")
    try:
        options = await generate_options(story)
        await state.update_data(ai_options=options)
        await state.set_state(ChapterStates.waiting_option)

        text = "<b>Выбери направление:</b>\n\n"
        for i, opt in enumerate(options, 1):
            text += f"<b>{i}.</b> {opt}\n\n"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Вариант {i}", callback_data=f"opt:{i - 1}")]
                for i in range(1, len(options) + 1)
            ]
        )
        await wait_msg.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

    except Exception as e:
        await wait_msg.edit_text(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("opt:"))
async def cb_pick_option(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    options = data.get("ai_options", [])

    if idx >= len(options):
        await callback.message.answer("Что-то пошло не так. Попробуй /next")
        return

    direction = options[idx]
    await callback.message.edit_reply_markup(reply_markup=None)

    user_id = callback.from_user.id
    story = get_current_story(user_id)
    if not story:
        return

    await state.clear()
    await generate_and_send(callback.message, state, user_id, story, direction)


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
