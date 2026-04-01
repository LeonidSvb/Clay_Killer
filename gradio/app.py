import gradio as gr
import openai
import os
import time
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

MODELS = {
    "Llama 3.1 70B":     {"id": "meta-llama/llama-3.1-70b-instruct",     "in": 0.35,  "out": 0.40},
    "Llama 3.3 70B":     {"id": "meta-llama/llama-3.3-70b-instruct",     "in": 0.35,  "out": 0.40},
    "Llama 4 Maverick":  {"id": "meta-llama/llama-4-maverick",            "in": 0.20,  "out": 0.60},
    "GPT-4o":            {"id": "openai/gpt-4o",                          "in": 2.50,  "out": 10.0},
    "GPT-4o Mini":       {"id": "openai/gpt-4o-mini",                     "in": 0.15,  "out": 0.60},
    "GPT-OSS 120B":      {"id": "openai/gpt-oss-120b",                    "in": 0.039, "out": 0.19},
    "DeepSeek R1":       {"id": "deepseek/deepseek-r1",                   "in": 0.55,  "out": 2.19},
    "DeepSeek V3":       {"id": "deepseek/deepseek-chat-v3-0324",         "in": 0.27,  "out": 1.10},
    "Qwen 2.5 72B":      {"id": "qwen/qwen-2.5-72b-instruct",             "in": 0.35,  "out": 0.40},
    "Mistral Large":     {"id": "mistral/mistral-large-2411",              "in": 2.0,   "out": 6.0},
    "Claude 3.5 Haiku":  {"id": "anthropic/claude-3-5-haiku",             "in": 0.80,  "out": 4.0},
    "Claude Sonnet 4.5": {"id": "anthropic/claude-sonnet-4-5",            "in": 3.0,   "out": 15.0},
    "Gemini 2.0 Flash":  {"id": "google/gemini-2.0-flash-001",            "in": 0.10,  "out": 0.40},
}
MODEL_NAMES = list(MODELS.keys())

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

DEFAULT_SYS_1 = "You are a B2B cold email expert writing short, personalized icebreakers for outreach campaigns."
DEFAULT_SYS_2 = "You are a top 1% SDR at a YC-backed startup. Write icebreakers that sound human, specific, never salesy. One sentence max. Reference something real about the prospect."
DEFAULT_SCORE_PROMPT = """You are an expert cold email icebreaker evaluator for B2B sales.
Score each icebreaker on these criteria (1-10 each):
- personalization: how specific/tailored to the lead (not generic)
- relevance: relates to their business/role/context
- tone: natural, not salesy, conversational
- hook: unique angle, sparks curiosity
- brevity: concise (ideal 1-2 sentences)

Respond ONLY with valid JSON:
{"personalization": 8, "relevance": 7, "tone": 9, "hook": 6, "brevity": 10, "overall": 8, "verdict": "Strong opener but could reference their product more specifically"}

No explanation outside JSON."""

DEFAULT_LEAD = """Name: Alex Rodriguez
Title: Director of Revenue Operations
Company: GrowthStack
Industry: B2B SaaS
LinkedIn post: Just hired 3 new RevOps analysts. Scaling fast!
Company size: 150 employees
Funding: Series B"""


# ── HELPERS ───────────────────────────────────────────────────────────────────

def fmt_cost(v):
    if v == 0:
        return "0"
    if v < 0.01:
        return f"{v:.8f}".rstrip("0")
    return f"{v:.4f}"


def make_range(lo, hi, step):
    vals, v = [], lo
    while v <= hi + 1e-9:
        vals.append(round(v, 3))
        v = round(v + step, 3)
    return vals


def parse_score_json(text):
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        return json.loads(text[s:e])
    except Exception:
        return {"personalization": 0, "relevance": 0, "tone": 0,
                "hook": 0, "brevity": 0, "overall": 0,
                "verdict": f"parse error: {text[:60]}"}


# ── API CALL ──────────────────────────────────────────────────────────────────

def call_model(model_key, sys_prompt, user_prompt, temperature, top_p=1.0):
    info = MODELS[model_key]
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=info["id"],
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            top_p=top_p,
            extra_body={"provider": {"sort": "throughput"}},
        )
        elapsed = time.time() - start
        t_in  = resp.usage.prompt_tokens
        t_out = resp.usage.completion_tokens
        cost  = (t_in * info["in"] + t_out * info["out"]) / 1_000_000
        return {
            "text": resp.choices[0].message.content or "",
            "tokens_in": t_in, "tokens_out": t_out,
            "cost_float": cost, "cost_usd": fmt_cost(cost),
            "latency_s": round(elapsed, 2),
            "tps": round(t_out / elapsed, 1) if elapsed > 0 else 0,
            "error": None,
        }
    except Exception as e:
        return {
            "text": "", "tokens_in": 0, "tokens_out": 0,
            "cost_float": 0.0, "cost_usd": "0",
            "latency_s": round(time.time() - start, 2), "tps": 0,
            "error": str(e),
        }


# ── PLAN CALCULATOR ───────────────────────────────────────────────────────────

def calculate_plan(gen_models, t_min, t_max, t_step, use_sys2, n_ice, judge_models):
    if not gen_models or not judge_models:
        return "_Выбери хотя бы одну модель генерации и одного судью_"

    temps = make_range(t_min, t_max, t_step)
    n_sys = 2 if use_sys2 else 1

    n_gen_calls  = len(gen_models) * len(temps) * n_sys
    total_ice    = n_gen_calls * int(n_ice)
    n_eval_calls = total_ice * len(judge_models)
    total_calls  = n_gen_calls + n_eval_calls

    avg_gi = sum(MODELS[m]["in"]  for m in gen_models) / len(gen_models)
    avg_go = sum(MODELS[m]["out"] for m in gen_models) / len(gen_models)
    avg_ji = sum(MODELS[j]["in"]  for j in judge_models) / len(judge_models)
    avg_jo = sum(MODELS[j]["out"] for j in judge_models) / len(judge_models)

    tgi, tgo = 450, int(n_ice) * 22
    tji, tjo = 520, 110

    cost_gen   = n_gen_calls  * (tgi * avg_gi + tgo * avg_go) / 1_000_000
    cost_judge = n_eval_calls * (tji * avg_ji + tjo * avg_jo) / 1_000_000
    total_cost = cost_gen + cost_judge

    t_str = " / ".join(str(t) for t in temps)

    lines = [
        f"**{len(gen_models)} моделей x {len(temps)} темп ({t_str}) x {n_sys} промпт = {n_gen_calls} конфигов**",
        f"{n_gen_calls} x {int(n_ice)} = **{total_ice} выходов**",
        f"{total_ice} x {len(judge_models)} судей = **{n_eval_calls} оценок** | Всего вызовов: **{total_calls}**",
        "",
        f"Генерация: ~**${fmt_cost(cost_gen)}** | Оценка: ~**${fmt_cost(cost_judge)}** | Итого: ~**${fmt_cost(total_cost)}**",
        f"_Расчёт приблизительный: {tgi}+{tgo} tok на генерацию, {tji}+{tjo} tok на оценку_",
    ]
    return "\n".join(lines)


# ── MAIN EXPERIMENT ───────────────────────────────────────────────────────────

def run_experiment(
    gen_models, sys_prompt_1, sys_prompt_2, use_sys2,
    t_min, t_max, t_step,
    n_ice, lead_data,
    judge_models, score_prompt,
    progress=gr.Progress(),
):
    if not gen_models:
        return [pd.DataFrame()] * 5 + ["Выбери модели генерации", "{}",
                gr.update(choices=["Все модели"], value="Все модели")]
    if not judge_models:
        return [pd.DataFrame()] * 5 + ["Выбери судей", "{}",
                gr.update(choices=["Все модели"], value="Все модели")]

    temps = make_range(t_min, t_max, t_step)
    sys_variants = [(1, sys_prompt_1)]
    if use_sys2 and sys_prompt_2.strip():
        sys_variants.append((2, sys_prompt_2))

    gen_configs = [
        (model, temp, idx, sp)
        for model in gen_models
        for temp in temps
        for idx, sp in sys_variants
    ]

    n_gen     = len(gen_configs)
    n_ice_int = int(n_ice)
    gen_prompt = (
        f"Generate {n_ice_int} unique cold email icebreakers for this lead. "
        f"Output ONLY the icebreakers, one per line, no numbering, no bullets, no dashes.\n\n"
        f"Lead info:\n{lead_data}"
    )

    # ── GENERATION ────────────────────────────────────────────────────────────
    progress(0, desc="Запуск генерации...")
    generated = []
    gen_tok_in = gen_tok_out = 0
    gen_cost = 0.0

    def do_gen(cfg):
        model, temp, sp_idx, sp_text = cfg
        r = call_model(model, sp_text, gen_prompt, temp)
        lines = []
        if not r["error"]:
            lines = [l.strip() for l in r["text"].strip().split("\n") if l.strip()][:n_ice_int]
        return {"model": model, "temp": temp, "sp_idx": sp_idx,
                "icebreakers": lines, "meta": r}

    gen_done = 0
    with ThreadPoolExecutor(max_workers=min(20, n_gen)) as ex:
        futures = [ex.submit(do_gen, cfg) for cfg in gen_configs]
        for fut in as_completed(futures):
            res = fut.result()
            generated.append(res)
            gen_tok_in  += res["meta"]["tokens_in"]
            gen_tok_out += res["meta"]["tokens_out"]
            gen_cost    += res["meta"]["cost_float"]
            gen_done    += 1
            progress(gen_done / (n_gen * 2), desc=f"Генерация: {gen_done}/{n_gen} конфигов")

    total_ice_count = sum(len(g["icebreakers"]) for g in generated)

    # ── SCORING ───────────────────────────────────────────────────────────────
    score_pairs = [
        (g["model"], g["temp"], g["sp_idx"], ice, judge)
        for g in generated
        for ice in g["icebreakers"]
        for judge in judge_models
    ]
    n_eval = len(score_pairs)
    eval_done = 0
    eval_tok_in = eval_tok_out = 0
    eval_cost = 0.0
    raw_results = []

    def do_score(model, temp, sp_idx, ice, judge):
        r = call_model(judge, score_prompt, f"Icebreaker to evaluate:\n{ice}", 0.1)
        return model, temp, sp_idx, ice, judge, r

    with ThreadPoolExecutor(max_workers=min(30, max(n_eval, 1))) as ex:
        futures = [ex.submit(do_score, *p) for p in score_pairs]
        for fut in as_completed(futures):
            model, temp, sp_idx, ice, judge, r = fut.result()
            if not r["error"]:
                eval_tok_in  += r["tokens_in"]
                eval_tok_out += r["tokens_out"]
                eval_cost    += r["cost_float"]
                sd = parse_score_json(r["text"])
            else:
                sd = {"personalization": 0, "relevance": 0, "tone": 0,
                      "hook": 0, "brevity": 0, "overall": 0, "verdict": f"err: {r['error']}"}

            raw_results.append({
                "Generator":  model,
                "Temp":       temp,
                "Prompt":     f"P{sp_idx}",
                "Judge":      judge,
                "Icebreaker": ice[:110] + ("..." if len(ice) > 110 else ""),
                "Pers.":      sd.get("personalization", 0),
                "Relev.":     sd.get("relevance", 0),
                "Tone":       sd.get("tone", 0),
                "Hook":       sd.get("hook", 0),
                "Brevity":    sd.get("brevity", 0),
                "Score":      sd.get("overall", 0),
                "Verdict":    sd.get("verdict", ""),
            })
            eval_done += 1
            progress(0.5 + eval_done / (n_eval * 2), desc=f"Оценка: {eval_done}/{n_eval}")

    progress(1.0, desc="Готово!")

    if not raw_results:
        return [pd.DataFrame()] * 5 + ["Нет результатов", "{}",
                gr.update(choices=["Все модели"], value="Все модели")]

    df = pd.DataFrame(raw_results)
    sc = ["Pers.", "Relev.", "Tone", "Hook", "Brevity", "Score"]

    # По моделям
    df_model = df.groupby("Generator")[sc].mean().round(2).reset_index()
    df_model.columns = ["Generator"] + [f"avg {c}" for c in sc]
    cnt = df.groupby("Generator")["Icebreaker"].nunique()
    df_model["Ice."] = df_model["Generator"].map(cnt).fillna(0).astype(int)
    df_model = df_model.sort_values("avg Score", ascending=False).reset_index(drop=True)

    # Топ конфигов
    df_cfg = df.groupby(["Generator", "Temp", "Prompt"])[sc].mean().round(2).reset_index()
    df_cfg.columns = ["Generator", "Temp", "Prompt"] + [f"avg {c}" for c in sc]
    df_cfg = df_cfg.sort_values("avg Score", ascending=False).reset_index(drop=True)

    # По судьям
    df_judge = df.groupby("Judge")[sc].mean().round(2).reset_index()
    df_judge.columns = ["Judge"] + [f"avg {c}" for c in sc]
    df_judge["Scored"] = df.groupby("Judge").size().values
    df_judge = df_judge.sort_values("avg Score", ascending=False).reset_index(drop=True)

    # Топ выходов
    df_top = df.groupby("Icebreaker")["Score"].mean().round(2).reset_index()
    df_top.columns = ["Icebreaker", "avg Score"]
    df_top = df_top.nlargest(25, "avg Score").reset_index(drop=True)

    total_cost = gen_cost + eval_cost
    session_info = (
        f"Генерация: {gen_tok_in} in / {gen_tok_out} out / ${fmt_cost(gen_cost)}   |   "
        f"Оценка: {eval_tok_in} in / {eval_tok_out} out / ${fmt_cost(eval_cost)}   |   "
        f"Итого: {gen_tok_in+eval_tok_in} in / {gen_tok_out+eval_tok_out} out / ${fmt_cost(total_cost)}"
    )

    session_json = json.dumps({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "gen_models": gen_models, "temperatures": temps,
            "sys_prompt_1": sys_prompt_1,
            "sys_prompt_2": sys_prompt_2 if use_sys2 else None,
            "score_prompt": score_prompt, "lead_data": lead_data,
            "n_ice_per_config": n_ice_int, "judge_models": judge_models,
        },
        "stats": {
            "gen_calls": n_gen, "total_outputs": total_ice_count,
            "eval_calls": n_eval,
            "gen_tokens_in": gen_tok_in, "gen_tokens_out": gen_tok_out,
            "gen_cost_usd": round(gen_cost, 8),
            "eval_tokens_in": eval_tok_in, "eval_tokens_out": eval_tok_out,
            "eval_cost_usd": round(eval_cost, 8),
            "total_cost_usd": round(total_cost, 8),
        },
        "results": raw_results,
    }, indent=2, ensure_ascii=False)

    model_choices = ["Все модели"] + sorted(df["Generator"].unique().tolist())
    return (df, df_model, df_cfg, df_judge, df_top,
            session_info, session_json,
            gr.update(choices=model_choices, value="Все модели"))


def filter_detail(results_json, selected_model):
    if not results_json or results_json == "{}":
        return pd.DataFrame()
    try:
        data = json.loads(results_json)
        df = pd.DataFrame(data.get("results", []))
        if selected_model and selected_model != "Все модели":
            df = df[df["Generator"] == selected_model]
        return df.sort_values("Score", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def save_json(session_json):
    if not session_json or session_json == "{}":
        return "Нет данных — сначала запусти эксперимент"
    fname = f"scoring_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path  = os.path.join(RESULTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(session_json)
    return f"Сохранено: {path}"


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="LLM Testing Lab") as demo:

    session_state = gr.State("{}")

    gr.Markdown("# LLM Testing Lab")

    with gr.Accordion("Настройки эксперимента", open=True):
        with gr.Row():

            with gr.Column(scale=1):
                gr.Markdown("**Генераторы**")
                gen_models_dd = gr.Dropdown(
                    MODEL_NAMES, multiselect=True,
                    value=["Llama 3.3 70B", "GPT-4o Mini", "Gemini 2.0 Flash"],
                    label="Модели генерации",
                )
                with gr.Row():
                    t_min  = gr.Slider(0.0, 2.0, value=0.5, step=0.1, label="Temp min")
                    t_max  = gr.Slider(0.0, 2.0, value=1.0, step=0.1, label="Temp max")
                    t_step = gr.Dropdown([0.1, 0.2, 0.3, 0.5, 1.0], value=0.5, label="Step")
                n_ice = gr.Slider(3, 30, value=5, step=1, label="Выходов на конфиг")

            with gr.Column(scale=1):
                gr.Markdown("**Промпты и данные**")
                sys_prompt_1 = gr.Textbox(DEFAULT_SYS_1, label="System prompt 1", lines=3)
                use_sys2     = gr.Checkbox(False, label="Тестировать второй вариант промпта")
                sys_prompt_2 = gr.Textbox(DEFAULT_SYS_2, label="System prompt 2", lines=3, visible=False)
                lead_data    = gr.Textbox(DEFAULT_LEAD, label="Данные лида / входные данные", lines=8)
                use_sys2.change(lambda v: gr.update(visible=v), inputs=[use_sys2], outputs=[sys_prompt_2])

            with gr.Column(scale=1):
                gr.Markdown("**Судьи**")
                judge_models_dd = gr.Dropdown(
                    MODEL_NAMES, multiselect=True,
                    value=["GPT-4o Mini", "Gemini 2.0 Flash"],
                    label="Модели-судьи",
                )
                score_prompt = gr.Textbox(DEFAULT_SCORE_PROMPT, label="Промпт судьи", lines=13)

    with gr.Group():
        plan_box = gr.Markdown("_Выбери настройки выше_")

    plan_inputs = [gen_models_dd, t_min, t_max, t_step, use_sys2, n_ice, judge_models_dd]
    for inp in plan_inputs:
        inp.change(calculate_plan, inputs=plan_inputs, outputs=[plan_box])

    btn_run = gr.Button("Запустить эксперимент", variant="primary", size="lg")

    session_info_box = gr.Textbox(label="Статистика сессии", interactive=False, lines=2)

    with gr.Tabs():

        with gr.TabItem("По моделям"):
            table_by_model = gr.Dataframe(label="Сводка по моделям", wrap=True)
            model_drill    = gr.Dropdown(["Все модели"], value="Все модели", label="Детализация по модели")
            table_drill    = gr.Dataframe(label="Все оценки для выбранной модели", wrap=True)

        with gr.TabItem("Топ конфигов"):
            table_by_config = gr.Dataframe(label="Ранжирование конфигов", wrap=True)

        with gr.TabItem("По судьям"):
            table_by_judge = gr.Dataframe(label="Сводка по судьям", wrap=True)

        with gr.TabItem("Топ выходов"):
            table_top = gr.Dataframe(label="Топ 25 по среднему баллу", wrap=True)

        with gr.TabItem("Все результаты"):
            table_detail = gr.Dataframe(label="Полная таблица", wrap=True)

    with gr.Row():
        btn_save   = gr.Button("Сохранить в JSON", variant="secondary")
        save_label = gr.Textbox(label="", interactive=False, scale=4)

    run_outputs = [
        table_detail, table_by_model, table_by_config,
        table_by_judge, table_top,
        session_info_box, session_state, model_drill,
    ]

    btn_run.click(
        run_experiment,
        inputs=[
            gen_models_dd, sys_prompt_1, sys_prompt_2, use_sys2,
            t_min, t_max, t_step,
            n_ice, lead_data,
            judge_models_dd, score_prompt,
        ],
        outputs=run_outputs,
    )

    model_drill.change(
        filter_detail,
        inputs=[session_state, model_drill],
        outputs=[table_drill],
    )

    btn_save.click(save_json, inputs=[session_state], outputs=[save_label])

if __name__ == "__main__":
    demo.launch(server_port=7860, share=False, show_error=True, theme=gr.themes.Soft())
