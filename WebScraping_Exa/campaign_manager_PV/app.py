import streamlit as st

st.set_page_config(
    page_title="Campaign Manager",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Campaign Manager — PlusVibe")
st.caption("Пропускная способность, расписание и конфликты email-кампаний")

st.markdown("""
Навигация в боковом меню:

- **Overview** — таблица кампаний: daily cap, лиды, ETA, конфликты аккаунтов
- **Timeline** — projected sends по дням на 30 дней вперёд
- **Simulator** — что будет если запустить паузнутую кампанию в X дату
""")
