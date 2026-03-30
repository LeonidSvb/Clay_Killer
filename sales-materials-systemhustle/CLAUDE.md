# System Hustle — Project Map

## Что это

Инструментарий для signal-based BD в рекрутинге. Леонид (основатель System Hustle)
мониторит рыночные сигналы и вводит рекрутеров как warm referral в нужный момент.

---

## Файлы

### Основной дек
**`signal-deck.html`** — питч дек для продаж, захосчен на GitHub Pages.
- 7 слайдов: Pain → Bleed → Why DIY → Mechanism → Framing → Urgency → Offer
- Защищён паролем (клиентский gate, не серверный)
- Нише-селектор с 9 шаблонами + Custom prospect JSON panel
- Live-калькулятор на слайде 2 (часы × ставка × fee)
- Click-to-reveal на всех визуализациях (Леонид делает скрин-шеринг и кликает сам)

**`signal_pitch_light.html`** — рабочая локальная копия дека (идентична signal-deck.html).
Редактируй этот файл, потом копируй в signal-deck.html перед деплоем.

**`signal-playbook.html`** — отдельный документ, не трогать, это другое.

### Пресейл-ресёрч
**`research_prompt.txt`** — промпт для подготовки к звонку через Exa AI.
Включает: методологию поиска (4 параллельных запроса), критерии оценки источников,
и DECK INJECTION блок — JSON который вставляется в Custom panel дека.

**`call_prep_rob.md`** — подготовка к звонку Rob Berton / Locum Tenens USA.
Oregon, locum tenens, EM + Pain Management. Rob — owner, делает BD сам.
Внизу файла: готовый DECK INJECTION JSON.

**`call_prep_vincent.md`** — подготовка к звонку Vincent Burger / NorTek Medical.
Houston TX, 28 человек, VA/DoD/correctional. Vincent — VP Ops, не decision maker.
CEO Siva Tayi — финальный decision maker, нужен на второй звонок.
Внизу файла: готовый DECK INJECTION JSON.

---

## Воркфлоу — подготовка к звонку

1. Открой `call_prep_[name].md` — прочитай перед звонком
2. Скопируй JSON из секции **DECK INJECTION** внизу файла
3. Открой `signal-deck.html` → кнопка **⊞ Niche** → **Custom prospect →**
4. Вставь JSON в textarea → **Apply to deck**
5. Дек обновился: слайд 4 (scoring table) + калькулятор + кнопка показывает имя проспекта

---

## Воркфлоу — ресёрч нового проспекта

1. Возьми промпт из `research_prompt.txt`
2. Вставь данные проспекта (имя, сайт, LinkedIn)
3. Запусти через Claude с Exa AI (ключ в `.env` → `EXA_API_KEY`)
4. Получи DECK INJECTION JSON в конце вывода
5. Создай `call_prep_[name].md` по образцу существующих файлов

---

## Exa AI

- Endpoint: `https://api.exa.ai/search`
- Ключ: `.env` → `EXA_API_KEY` (не коммитить, в .gitignore)
- Документация: https://docs.exa.ai
- Стратегия: 4 параллельных запроса (neural + keyword), детали в `research_prompt.txt`

---

## Нише-шаблоны в деке

| Key | Название | Default fee |
|---|---|---|
| `generic` | Generic / Other | $20,000 |
| `exec-tech` | Executive search — tech | $35,000 |
| `exec-nontech` | Executive search — non-tech | $40,000 |
| `it-software` | IT & Software recruiting | $25,000 |
| `sales-gtm` | Sales & GTM recruiting | $22,000 |
| `finance` | Finance & Accounting | $28,000 |
| `manufacturing` | Manufacturing & Industrial | $12,000 |
| `healthcare` | Healthcare staffing | $15,000 |
| `va-staffing` | VA & Virtual assistant | $5,000 |

Custom JSON через панель перезаписывает любую нишу без изменения файла.

---

## Питч — ключевые различия по типу проспекта

**Owner/solo (тип Rob):** боль — личное время на BD. Питч: "ты тратишь своё время впустую."
Главный слайд — Slide 2 (калькулятор). Decision maker — он сам.

**VP/Operations (тип Vincent):** боль — эффективность BD команды. Питч: "Justin звонит не тем людям не в то время."
Главный слайд — Slide 4 (scoring table). Decision maker — CEO, нужен на второй звонок.
