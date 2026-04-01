import gradio as gr

from config import MODEL_NAMES, MAX_PROMPT_SLOTS, DEFAULT_PROMPT, DEFAULT_JUDGE_PROMPT
from core import (
    calculate_plan, run_experiment, build_dataframe, apply_filters,
    get_numeric_cols, build_summary, list_prompts, load_prompt, save_prompt,
)


# ── HELPERS ───────────────────────────────────────────────────────────────────

def update_plan(models, p1, p2, p3, p4, p5, temperature, n_outputs, judge_models):
    return calculate_plan(
        models or [], [p1, p2, p3, p4, p5],
        temperature, n_outputs, judge_models or [],
    )


def add_prompt_slot(count):
    count = min(count + 1, MAX_PROMPT_SLOTS)
    group_updates = [gr.update(visible=(i < count)) for i in range(MAX_PROMPT_SLOTS)]
    return group_updates + [count]


def load_prompt_into_slot(name, current_text):
    if not name:
        return current_text
    try:
        return load_prompt(name)
    except Exception:
        return current_text


def do_save_prompt(name, text):
    if not name or not name.strip():
        return gr.update(), "Введи название"
    path = save_prompt(name, text)
    new_choices = [""] + list_prompts()
    return gr.update(choices=new_choices, value=name), f"Сохранено: {path}"


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="LLM Testing Lab") as demo:

    raw_state    = gr.State([])
    prompt_count = gr.State(1)

    gr.Markdown("# LLM Testing Lab")

    # ── SETTINGS ──────────────────────────────────────────────────────────────
    with gr.Accordion("Настройки", open=True) as settings_accordion:
        with gr.Row():

            # LEFT — prompts
            with gr.Column(scale=2):
                gr.Markdown("**Промпты**")

                slot_groups  = []
                prompt_slots = []
                load_dds     = []

                for i in range(MAX_PROMPT_SLOTS):
                    with gr.Group(visible=(i == 0)) as grp:
                        with gr.Row():
                            load_dd = gr.Dropdown(
                                choices=[""] + list_prompts(),
                                label=f"Загрузить {i+1}",
                                value="", scale=3,
                            )
                            save_name_inp = gr.Textbox(
                                placeholder="Название",
                                label="", scale=2, show_label=False,
                            )
                            btn_save_p = gr.Button("Сохранить", size="sm", scale=1)
                        txt = gr.Textbox(
                            value=DEFAULT_PROMPT if i == 0 else "",
                            label=f"Промпт {i + 1}",
                            lines=5,
                        )
                        save_lbl = gr.Textbox(
                            value="", label="", interactive=False, lines=1,
                        )

                    slot_groups.append(grp)
                    prompt_slots.append(txt)
                    load_dds.append(load_dd)

                    load_dd.change(
                        load_prompt_into_slot,
                        inputs=[load_dd, txt],
                        outputs=[txt],
                    )
                    btn_save_p.click(
                        do_save_prompt,
                        inputs=[save_name_inp, txt],
                        outputs=[load_dd, save_lbl],
                    )

                btn_add = gr.Button("+ промпт", size="sm", variant="secondary")

            # CENTER — models & params
            with gr.Column(scale=1):
                gr.Markdown("**Модели и параметры**")
                models_dd = gr.Dropdown(
                    MODEL_NAMES, multiselect=True,
                    value=["Llama 3.3 70B", "GPT-4o Mini", "Gemini 2.0 Flash"],
                    label="Модели генерации",
                )
                temperature = gr.Slider(
                    0.0, 2.0, value=0.7, step=0.05, label="Температура",
                )
                n_outputs = gr.Slider(
                    5, 50, value=15, step=5, label="Выходов на конфиг",
                )

            # RIGHT — judge
            with gr.Column(scale=1):
                gr.Markdown("**Судья**")
                judge_dd = gr.Dropdown(
                    MODEL_NAMES, multiselect=True,
                    value=["GPT-4o Mini"],
                    label="Модель-судья",
                )
                with gr.Row():
                    judge_load_dd = gr.Dropdown(
                        choices=[""] + list_prompts(),
                        label="Загрузить промпт судьи",
                        value="", scale=3,
                    )
                    judge_save_name = gr.Textbox(
                        placeholder="Название", label="", scale=2, show_label=False,
                    )
                    btn_save_judge = gr.Button("Сохранить", size="sm", scale=1)
                judge_prompt = gr.Textbox(
                    DEFAULT_JUDGE_PROMPT, label="Промпт судьи", lines=10,
                )
                judge_save_lbl = gr.Textbox(
                    value="", label="", interactive=False, lines=1,
                )

    # ── PLAN ──────────────────────────────────────────────────────────────────
    plan_box = gr.Markdown("_Заполни настройки выше_")

    btn_run = gr.Button("Запустить эксперимент", variant="primary", size="lg")

    # ── STATUS ────────────────────────────────────────────────────────────────
    status_box = gr.Textbox(label="Статус", interactive=False, lines=2)

    # ── FILTERS ───────────────────────────────────────────────────────────────
    with gr.Row():
        filter_col    = gr.Dropdown(
            choices=["overall"], value="overall",
            label="Фильтр по критерию", scale=2,
        )
        filter_min    = gr.Slider(0, 10, value=0,  step=0.5, label="Min", scale=2)
        filter_max    = gr.Slider(0, 10, value=10, step=0.5, label="Max", scale=2)
        filter_model  = gr.Dropdown(
            ["Все модели"], value="Все модели", label="Модель", scale=2,
        )
        filter_prompt = gr.Dropdown(
            ["Все промпты"], value="Все промпты", label="Промпт", scale=2,
        )

    # ── TABLE ─────────────────────────────────────────────────────────────────
    results_table = gr.Dataframe(
        label="Результаты", wrap=True, interactive=False,
    )

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    summary_box = gr.Markdown("")

    # ── EVENTS ────────────────────────────────────────────────────────────────

    # add prompt slot — update Group visibility (fix: outputs are groups not textboxes)
    btn_add.click(
        add_prompt_slot,
        inputs=[prompt_count],
        outputs=slot_groups + [prompt_count],
    )

    # judge prompt load/save
    judge_load_dd.change(
        load_prompt_into_slot,
        inputs=[judge_load_dd, judge_prompt],
        outputs=[judge_prompt],
    )
    btn_save_judge.click(
        do_save_prompt,
        inputs=[judge_save_name, judge_prompt],
        outputs=[judge_load_dd, judge_save_lbl],
    )

    # plan auto-update
    plan_inputs = [models_dd] + prompt_slots + [temperature, n_outputs, judge_dd]
    for inp in plan_inputs:
        inp.change(update_plan, inputs=plan_inputs, outputs=[plan_box])

    # collapse settings on run start
    btn_run.click(
        lambda: gr.update(open=False),
        inputs=[], outputs=[settings_accordion],
    )

    # run experiment
    def run_wrapper(models, p1, p2, p3, p4, p5,
                    temperature, n_outputs, judge_models, judge_prompt):
        prompts   = [p1, p2, p3, p4, p5]
        prev_rows = []

        for update in run_experiment(
            models or [], prompts, temperature, n_outputs,
            judge_models or [], judge_prompt,
        ):
            if update["error"]:
                yield (
                    update["status"], gr.update(),
                    gr.update(), gr.update(), gr.update(),
                    prev_rows, "",
                )
                return

            rows = update["rows"]
            if rows:
                prev_rows = rows
                df         = build_dataframe(rows)
                num_cols   = get_numeric_cols(rows)
                models_in  = ["Все модели"] + sorted({r["model"] for r in rows})
                prompts_in = (
                    ["Все промпты"]
                    + [f"Промпт {i}" for i in sorted({r["prompt_idx"] for r in rows})]
                )
                yield (
                    update["status"],
                    df,
                    gr.update(choices=num_cols, value="overall"),
                    gr.update(choices=models_in,  value="Все модели"),
                    gr.update(choices=prompts_in, value="Все промпты"),
                    rows,
                    build_summary(rows),
                )
            else:
                yield (
                    update["status"], gr.update(),
                    gr.update(), gr.update(), gr.update(),
                    prev_rows, "",
                )

    btn_run.click(
        run_wrapper,
        inputs=[models_dd] + prompt_slots + [temperature, n_outputs, judge_dd, judge_prompt],
        outputs=[
            status_box, results_table,
            filter_col, filter_model, filter_prompt,
            raw_state, summary_box,
        ],
        show_progress=False,
    )

    # filters → re-render table
    filter_inputs = [raw_state, filter_col, filter_min, filter_max,
                     filter_model, filter_prompt]
    for f in [filter_col, filter_min, filter_max, filter_model, filter_prompt]:
        f.change(apply_filters, inputs=filter_inputs, outputs=[results_table])


if __name__ == "__main__":
    demo.launch(server_port=7860, share=False, show_error=True, theme=gr.themes.Soft())
