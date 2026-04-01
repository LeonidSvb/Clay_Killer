from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from logic.storage import (
    get_current_story,
    get_all_stories,
    load_user_data,
    save_story,
    set_current_story,
    delete_story,
)
from logic.state import rollback_chapter, add_chapter, apply_summary
from logic.generate import generate_chapter
from logic.summarize import summarize_chapter
from handlers.chapter import send_chapter

router = Router()


def stories_keyboard(stories: list, current_id: str) -> InlineKeyboardMarkup:
    rows = []
    for i, s in enumerate(stories, 1):
        marker = " (активная)" if s["id"] == current_id else ""
        chapter_count = s["state"].get("chapter_count", 0)
        rows.append([
            InlineKeyboardButton(
                text=f"{i}. {s['title']}{marker} — {chapter_count} гл.",
                callback_data=f"story:load:{s['id']}"
            ),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=f"story:del:{s['id']}"
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("list"))
async def cmd_list(message: Message):
    user_id = message.from_user.id
    stories = get_all_stories(user_id)
    data = load_user_data(user_id)
    current_id = data.get("current_story_id")

    if not stories:
        await message.answer("У тебя пока нет историй. Создай через /start")
        return

    await message.answer(
        "<b>Твои истории:</b>\nНажми чтобы переключиться, или удали:",
        reply_markup=stories_keyboard(stories, current_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("story:load:"))
async def cb_story_load(callback: CallbackQuery):
    await callback.answer()
    story_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    if not set_current_story(user_id, story_id):
        await callback.message.answer("История не найдена.")
        return

    stories = get_all_stories(user_id)
    for s in stories:
        if s["id"] == story_id:
            chapter_count = s["state"].get("chapter_count", 0)
            await callback.message.edit_text(
                f'Активная история: <b>{s["title"]}</b>\n'
                f"Глав написано: {chapter_count}\n\n"
                f"Продолжить: /next",
                parse_mode="HTML",
            )
            return


@router.callback_query(F.data.startswith("story:del:"))
async def cb_story_delete(callback: CallbackQuery):
    await callback.answer()
    story_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    stories = get_all_stories(user_id)
    title = next((s["title"] for s in stories if s["id"] == story_id), story_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить", callback_data=f"story:delconfirm:{story_id}"),
        InlineKeyboardButton(text="Отмена",      callback_data="story:delcancel"),
    ]])
    await callback.message.answer(
        f'Удалить историю "<b>{title}</b>"? Это необратимо.',
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("story:delconfirm:"))
async def cb_story_delconfirm(callback: CallbackQuery):
    await callback.answer()
    story_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    stories = get_all_stories(user_id)
    title = next((s["title"] for s in stories if s["id"] == story_id), story_id)

    if delete_story(user_id, story_id):
        await callback.message.edit_text(f'История "<b>{title}</b>" удалена.', parse_mode="HTML")
        remaining = get_all_stories(user_id)
        if remaining:
            data = load_user_data(user_id)
            current_id = data.get("current_story_id")
            await callback.message.answer(
                "<b>Оставшиеся истории:</b>",
                reply_markup=stories_keyboard(remaining, current_id),
                parse_mode="HTML",
            )
    else:
        await callback.message.edit_text("История не найдена.")


@router.callback_query(F.data == "story:delcancel")
async def cb_story_delcancel(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()


@router.message(Command("load"))
async def cmd_load(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: /load &lt;номер или ID&gt;\nСписок: /list",
            parse_mode="HTML",
        )
        return

    arg = args[1].strip()
    stories = get_all_stories(user_id)
    if not stories:
        await message.answer("У тебя нет историй.")
        return

    story_id = None
    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(stories):
            story_id = stories[idx]["id"]
    if not story_id:
        for s in stories:
            if s["id"] == arg:
                story_id = s["id"]
                break

    if not story_id:
        await message.answer("История не найдена. Проверь /list")
        return

    set_current_story(user_id, story_id)
    for s in stories:
        if s["id"] == story_id:
            chapter_count = s["state"].get("chapter_count", 0)
            await message.answer(
                f'Активная история: <b>{s["title"]}</b>\n'
                f"Глав написано: {chapter_count}\n\n"
                f"Продолжить: /next",
                parse_mode="HTML",
            )
            return


@router.message(Command("regen"))
async def cmd_regen(message: Message, state: FSMContext):
    user_id = message.from_user.id
    story = get_current_story(user_id)

    if not story:
        await message.answer("Нет активной истории.")
        return

    if story["state"].get("chapter_count", 0) == 0:
        await message.answer("Нет глав для перегенерации.")
        return

    story = rollback_chapter(story)
    save_story(user_id, story)
    await state.clear()

    wait_msg = await message.answer("Перегенерирую последнюю главу...")
    try:
        chapter_text = await generate_chapter(story)
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
        await wait_msg.edit_text(f"Ошибка: {e}\n\nПопробуй /regen снова")
