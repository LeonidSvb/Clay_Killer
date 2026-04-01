import html

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from logic.storage import get_current_story
from handlers.chapter import split_text, format_chapter

router = Router()

PAGE_SIZE = 10


def get_chapter_title(text: str, idx: int) -> str:
    first_line = text.split("\n")[0].strip()
    if first_line.lower().startswith("глава"):
        return first_line[:50]
    return f"Глава {idx + 1}"


def chapters_list_keyboard(total: int, page: int) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    rows = []

    for i in range(start, end):
        rows.append([
            InlineKeyboardButton(
                text=f"{i + 1}. (загружается...)",
                callback_data=f"ch:read:{i}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=f"← {(page-1)*PAGE_SIZE+1}-{page*PAGE_SIZE}", callback_data=f"ch:page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text=f"{end+1}-{min(end+PAGE_SIZE, total)} →", callback_data=f"ch:page:{page+1}"))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def chapters_list_keyboard_titled(chapters: list, page: int) -> InlineKeyboardMarkup:
    total = len(chapters)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    rows = []

    for i in range(start, end):
        title = get_chapter_title(chapters[i], i)
        rows.append([
            InlineKeyboardButton(
                text=title[:60],
                callback_data=f"ch:read:{i}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text=f"← {(page-1)*PAGE_SIZE+1}–{page*PAGE_SIZE}",
            callback_data=f"ch:page:{page-1}"
        ))
    if end < total:
        nav.append(InlineKeyboardButton(
            text=f"{end+1}–{min(end+PAGE_SIZE, total)} →",
            callback_data=f"ch:page:{page+1}"
        ))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def chapter_nav_keyboard(idx: int, total: int) -> InlineKeyboardMarkup:
    row = []
    if idx > 0:
        row.append(InlineKeyboardButton(text=f"← Гл. {idx}", callback_data=f"ch:read:{idx-1}"))
    row.append(InlineKeyboardButton(text="К списку", callback_data="ch:list:0"))
    if idx < total - 1:
        row.append(InlineKeyboardButton(text=f"Гл. {idx+2} →", callback_data=f"ch:read:{idx+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


@router.message(Command("chapters"))
async def cmd_chapters(message: Message):
    user_id = message.from_user.id
    story = get_current_story(user_id)

    if not story:
        await message.answer("Нет активной истории. Создай через /start")
        return

    chapters = story.get("all_chapters", [])
    if not chapters:
        await message.answer(
            f'В истории "<b>{story["title"]}</b>" пока нет глав.\n\nНачни с /next',
            parse_mode="HTML",
        )
        return

    total = len(chapters)
    await message.answer(
        f'<b>{story["title"]}</b>\nГлав: {total}\n\nВыбери главу:',
        reply_markup=chapters_list_keyboard_titled(chapters, 0),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ch:page:"))
async def cb_chapters_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    story = get_current_story(user_id)

    if not story:
        return

    chapters = story.get("all_chapters", [])
    total = len(chapters)

    await callback.message.edit_text(
        f'<b>{story["title"]}</b>\nГлав: {total}\n\nВыбери главу:',
        reply_markup=chapters_list_keyboard_titled(chapters, page),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ch:read:"))
async def cb_read_chapter(callback: CallbackQuery):
    await callback.answer()
    idx = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    story = get_current_story(user_id)

    if not story:
        return

    chapters = story.get("all_chapters", [])
    total = len(chapters)

    if idx >= total:
        await callback.message.answer("Глава не найдена.")
        return

    chapter_text = chapters[idx]
    chunks = split_text(format_chapter(chapter_text))

    await callback.message.edit_reply_markup(reply_markup=None)

    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            await callback.message.answer(
                chunk,
                reply_markup=chapter_nav_keyboard(idx, total),
                parse_mode="HTML",
            )
        else:
            await callback.message.answer(chunk, parse_mode="HTML")


@router.callback_query(F.data.startswith("ch:list:"))
async def cb_back_to_list(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    story = get_current_story(user_id)

    if not story:
        return

    chapters = story.get("all_chapters", [])
    total = len(chapters)

    await callback.message.answer(
        f'<b>{story["title"]}</b>\nГлав: {total}\n\nВыбери главу:',
        reply_markup=chapters_list_keyboard_titled(chapters, page),
        parse_mode="HTML",
    )
