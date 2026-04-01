from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from states import QuizStates
from logic.storage import create_story, save_story
from logic.generate import generate_chapter
from logic.summarize import summarize_chapter
from logic.state import add_chapter, apply_summary
from handlers.chapter import send_chapter

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(QuizStates.genre)
    await message.answer(
        "Создаём новую историю. Отвечай на вопросы по одному.\n\n"
        "<b>Вопрос 1/4: Жанр, стиль и темп?</b>\n\n"
        "Примеры:\n"
        "- китайское ранобэ, быстрый темп, много экшена\n"
        "- тёмное фэнтези, медленно, детали и атмосфера\n"
        "- sci-fi боевик, средний темп\n\n"
        "Опиши как хочешь",
        parse_mode="HTML",
    )


@router.message(QuizStates.genre)
async def quiz_genre(message: Message, state: FSMContext):
    await state.update_data(genre=message.text)
    await state.set_state(QuizStates.hero)
    await message.answer(
        "<b>Вопрос 2/4: Кто главный герой?</b>\n\n"
        "Опиши:\n"
        "- имя\n"
        "- характер\n"
        "- цель",
        parse_mode="HTML",
    )


@router.message(QuizStates.hero)
async def quiz_hero(message: Message, state: FSMContext):
    await state.update_data(hero=message.text)
    await state.set_state(QuizStates.world)
    await message.answer(
        "<b>Вопрос 3/4: Опиши мир:</b>\n\n"
        "- где происходит\n"
        "- правила и особенности",
        parse_mode="HTML",
    )


@router.message(QuizStates.world)
async def quiz_world(message: Message, state: FSMContext):
    await state.update_data(world=message.text)
    await state.set_state(QuizStates.situation)
    await message.answer(
        "<b>Вопрос 4/4: С чего начинается история?</b>\n\n"
        "Стартовая ситуация для первой главы",
        parse_mode="HTML",
    )


@router.message(QuizStates.situation)
async def quiz_situation(message: Message, state: FSMContext):
    await state.update_data(situation=message.text)
    await state.set_state(QuizStates.title)
    await message.answer(
        "Отлично! Последнее — <b>название истории:</b>",
        parse_mode="HTML",
    )


@router.message(QuizStates.title)
async def quiz_title(message: Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip()
    await state.clear()

    story_state = {
        "genre": data["genre"],
        "hero": data["hero"],
        "world": data["world"],
        "start_situation": data["situation"],
        "characters": [],
        "chapter_count": 0,
    }

    user_id = message.from_user.id
    story = create_story(user_id, title, story_state)

    wait_msg = await message.answer(
        f'История "<b>{title}</b>" создана. Генерирую первую главу...',
        parse_mode="HTML",
    )

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
        await wait_msg.edit_text(
            f"Ошибка при генерации первой главы: {e}\n\nПопробуй /next"
        )
