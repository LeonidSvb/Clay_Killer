from aiogram.fsm.state import State, StatesGroup


class QuizStates(StatesGroup):
    genre = State()
    hero = State()
    world = State()
    situation = State()
    title = State()


class ChapterStates(StatesGroup):
    waiting_direction = State()
    waiting_custom = State()
    waiting_option = State()
    waiting_technique_choice = State()
