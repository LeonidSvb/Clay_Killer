---
id: "TASK-004"
title: "core/llm.py — OpenRouter LLM extraction с structured JSON output"
status: "planned"
priority: "P0"
labels: ["core", "llm", "openrouter"]
dependencies: ["TASK-002", "TASK-003"]
created: "2026-03-30"
---

# 1) High-Level Objective

Написать `core/llm.py` — async LLM клиент для OpenRouter.
Input: текст сайта + промпт из файла.
Output: dict с произвольными полями (определяется промптом) + всегда "confidence": 0-10.

Промпты читаются из папки prompts/ динамически.
system_context.txt добавляется к каждому вызову.

# 2) Background / Context

Из соседнего проекта ai_lead_processing (run_icebreakers.py):
  - httpx AsyncClient (не aiohttp — OpenRouter лучше с httpx)
  - "provider": {"sort": "throughput"} — ОБЯЗАТЕЛЬНО
  - concurrency=50 → ~14 leads/sec на коротких промптах
  - На длинных промптах (~15k chars) → оценка ~5-7/sec

Модель: openai/gpt-oss-120b
Context: 131,072 tokens (~393k chars) — наши 15k chars = 4% контекста.

# 3) Assumptions & Constraints

- Constraint: "provider": {"sort": "throughput"} всегда — без этого 7x медленнее
- Constraint: промпты в папке prompts/*.txt (не hardcode в коде)
- Constraint: JSON output — промпт должен требовать JSON, парсер robust
- ASSUMPTION: OPENROUTER_API_KEY в .env

# 4) Dependencies

- .env (OPENROUTER_API_KEY)
- prompts/system_context.txt
- prompts/company_profile.txt
- prompts/icp_score.txt
- prompts/company_full.txt
- core/scraper.py ScrapeResult _(read-only)_
- core/exa.py ExaResult _(read-only)_

# 5) Context Plan

**Beginning:**
- C:\Users\79818\Desktop\tests\ai_lead_processing\run_icebreakers.py _(read-only)_
- prompts/ (все файлы)

**End state:**
- core/llm.py
- prompts/system_context.txt
- prompts/company_profile.txt
- prompts/icp_score.txt
- prompts/company_full.txt

# 6) Low-Level Steps

1. **Типы:**
   ```python
   @dataclass
   class LLMResult:
       url: str
       data: dict          # произвольные поля из JSON ответа LLM
       confidence: int     # 0-10, всегда присутствует
       ok: bool
       error: str | None
       input_chars: int    # сколько chars текста подали на вход
       elapsed_ms: int
   ```

2. **Промпт-менеджер:**
   ```python
   PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

   def list_prompts() -> list[str]:
       # возвращает имена .txt файлов без расширения
       # исключает system_context

   def load_prompt(name: str) -> str:
       # читает prompts/{name}.txt

   def load_system_context() -> str:
       # читает prompts/system_context.txt
       # если файл не существует — возвращает ""

   def build_messages(prompt_name: str, text: str) -> list[dict]:
       # system message = system_context.txt
       # user message = prompt + "\n\n---\n\n" + text
       # возвращает [{"role": "system", ...}, {"role": "user", ...}]
   ```

3. **JSON парсер (robust):**
   ```python
   def parse_json_response(raw: str) -> dict:
       # 1. убрать ```json ... ``` обёртку если есть
       # 2. json.loads()
       # 3. если fail → попробовать найти {...} через regex
       # 4. если всё fail → вернуть {"raw": raw, "confidence": 0}
   ```

4. **Публичный API:**
   ```python
   async def extract(
       client: httpx.AsyncClient,
       sem: asyncio.Semaphore,
       url: str,
       text: str,
       prompt_name: str = "company_full",
       model: str = "openai/gpt-oss-120b",
       max_tokens: int = 800,
       temperature: float = 0.1,
   ) -> LLMResult: ...

   async def extract_batch(
       items: list[dict],   # [{"url": str, "text": str}, ...]
       prompt_name: str = "company_full",
       concurrency: int = 50,
       model: str = "openai/gpt-oss-120b",
   ) -> list[LLMResult]: ...
   ```

5. **OpenRouter запрос:**
   ```python
   payload = {
       "model": model,
       "messages": build_messages(prompt_name, text),
       "temperature": temperature,
       "max_tokens": max_tokens,
       "provider": {"sort": "throughput"},  # КРИТИЧНО
   }
   ```

6. **Промпты — написать содержимое файлов:**

   prompts/system_context.txt:
   ```
   You are analysing company websites for outreach qualification.
   Always respond with valid JSON only. No markdown, no explanation.
   The "confidence" field (0-10) reflects how much information was
   available to make accurate assessments. Low confidence = sparse website.
   ```

   prompts/company_profile.txt:
   ```
   Analyse the company website content below and produce a detailed factual summary.

   Return JSON:
   {
     "summary": "<800-1200 char factual description: what they do, services, geography, target clients, differentiators>",
     "confidence": <0-10>
   }

   Rules: facts only, no inference, no marketing language.
   If information is not present, say so explicitly in the summary.

   Website content:
   {text}
   ```

   prompts/icp_score.txt:
   ```
   Analyse the company website content and assess ICP fit.

   Return JSON:
   {
     "icp_fit": <0-10>,
     "icp_reasons": "<why this score, 1-2 sentences>",
     "b2b": <true|false>,
     "geography": "<countries/regions served>",
     "company_size_estimate": "<employees range if inferable, else null>",
     "confidence": <0-10>
   }

   Website content:
   {text}
   ```

   prompts/company_full.txt:
   ```
   Analyse the company website content below.

   Return JSON:
   {
     "summary": "<800-1200 char factual description>",
     "icp_fit": <0-10>,
     "icp_reasons": "<1-2 sentences>",
     "b2b": <true|false>,
     "geography": "<countries/regions>",
     "services": ["<service1>", "<service2>"],
     "target_market": "<who they sell to>",
     "company_size_estimate": "<if inferable>",
     "confidence": <0-10>
   }

   Rules: facts only. If not stated, use null.

   Website content:
   {text}
   ```

7. **CLI:**
   ```
   py core/llm.py --input file.csv --col company_website --limit 5 --prompt company_full
   ```
   Предполагает что текст уже есть (тестирует только LLM часть).
   Для теста — берёт Company Website URL, делает простой requests.get,
   подаёт текст в LLM.

# 8) Acceptance Criteria

- `from core.llm import extract_batch` работает
- На 5 URL возвращает валидный JSON с confidence полем
- parse_json_response не крашит на любом вводе
- list_prompts() возвращает ["company_profile", "icp_score", "company_full"]
- Время: 5 URL за < 15 сек

# 9) Testing Strategy

- 5 URL с готовым текстом (взять из TASK-002 или TASK-003 результатов)
- Проверить что все 3 промпта возвращают правильные поля
- Специально подать пустую строку → должен вернуть ok=True с низким confidence
- Проверить что "provider": "throughput" реально используется (замерить скорость)
