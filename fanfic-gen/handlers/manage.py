from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from states import ManageStates
from logic.storage import (
    get_current_story,
    get_all_stories,
    load_user_data,
    save_story,
    set_current_story,
    delete_story,
)
from logic.state import rollback_chapter
from logic.generate import generate_chapter
from handlers.chapter import send_chapter, get_main_keyboard

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
async def cb_story_delete(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    story_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    stories = get_all_stories(user_id)
    title = next((s["title"] for s in stories if s["id"] == story_id), story_id)

    await state.set_state(ManageStates.waiting_delete_confirm)
    await state.update_data(delete_story_id=story_id, delete_story_title=title)

    await callback.message.answer(
        f'Удаление необратимо.\n\n'
        f'Введи название истории полностью чтобы подтвердить:\n'
        f'<code>{title}</code>',
        parse_mode="HTML",
    )


@router.message(ManageStates.waiting_delete_confirm)
async def handle_delete_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    story_id = data.get("delete_story_id")
    title = data.get("delete_story_title", "")
    user_id = message.from_user.id

    if message.text.strip() != title:
        await message.answer(
            f'Название не совпадает. Введи точно:\n<code>{title}</code>\n\nИли напиши /list чтобы отменить.',
            parse_mode="HTML",
        )
        return

    await state.clear()

    if delete_story(user_id, story_id):
        await message.answer(f'История "<b>{title}</b>" удалена.', parse_mode="HTML")
        remaining = get_all_stories(user_id)
        if remaining:
            data = load_user_data(user_id)
            current_id = data.get("current_story_id")
            await message.answer(
                "<b>Оставшиеся истории:</b>",
                reply_markup=stories_keyboard(remaining, current_id),
                parse_mode="HTML",
            )
    else:
        await message.answer("История не найдена.")


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

    chapter_num = story["state"].get("chapter_count", 0) + 1
    await message.answer(
        f"Последняя глава откатана. Как перегенерировать главу {chapter_num}?",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
    )
    from states import ChapterStates
    await state.set_state(ChapterStates.waiting_direction)
