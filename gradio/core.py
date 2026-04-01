import os
import json
import time
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv

from config import MODELS, RESULTS_DIR, PROMPTS_DIR, API_TIMEOUT

load_dotenv()

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


# ── FORMATTING ────────────────────────────────────────────────────────────────

def fmt_cost(v: float) -> str:
    if v == 0:
        return "$0"
    if v < 0.01:
        return f"${v:.6f}".rstrip("0")
    return f"${v:.4f}"


# ── PROMPTS LIBRARY ───────────────────────────────────────────────────────────

def list_prompts() -> list:
    files = [f[:-4] for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")]
    return sorted(files)


def load_prompt(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    with open(path, encoding="utf-8") as f:
        return f.read()


def save_prompt(name: str, text: str) -> str:
    name = name.strip().replace("/", "-").replace("\\", "-")
    if not name:
        return "Введи название"
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ── API CALL ──────────────────────────────────────────────────────────────────

def call_model(model_key: str, prompt: str, temperature: float) -> dict:
    info = MODELS[model_key]
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=info["id"],
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=API_TIMEOUT,
            extra_body={"provider": {"sort": "throughput"}},
        )
        elapsed = time.time() - start
        t_in  = resp.usage.prompt_tokens
        t_out = resp.usage.completion_tokens
        cost  = (t_in * info["in"] + t_out * info["out"]) / 1_000_000
        return {
            "text":       resp.choices[0].message.content or "",
            "tokens_in":  t_in,
            "tokens_out": t_out,
            "cost_float": cost,
            "latency_s":  round(elapsed, 2),
            "error":      None,
        }
    except Exception as e:
        return {
            "text": "", "tokens_in": 0, "tokens_out": 0,
            "cost_float": 0.0, "latency_s": round(time.time() - start, 2),
            "error": str(e),
        }


# ── JUDGE OUTPUT PARSER ───────────────────────────────────────────────────────

def parse_judge_output(text: str) -> dict:
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s == -1 or e == 0:
            raise ValueError("no json")
        data = json.loads(text[s:e])
        # compute overall = mean of all numeric values (excluding key "overall")
        nums = [v for k, v in data.items()
                if isinstance(v, (int, float)) and k != "overall"]
        data["overall"] = round(sum(nums) / len(nums), 2) if nums else 0.0
        return data
    except Exception:
        return {"parse_error": text[:100], "overall": 0.0}


# ── PLAN CALCULATOR ───────────────────────────────────────────────────────────

def calculate_plan(models: list, prompts: list, temperature: float,
                   n_outputs: int, judge_models: list) -> str:
    active_prompts = [p for p in prompts if p and p.strip()]
    if not models or not active_prompts or not judge_models:
        return "_Выбери модели, заполни хотя бы один промпт и выбери судью_"

    n_configs  = len(models) * len(active_prompts)
    n_gen      = n_configs * n_outputs
    n_eval     = n_gen * len(judge_models)
    total      = n_gen + n_eval

    avg_gi = sum(MODELS[m]["in"]  for m in models) / len(models)
    avg_go = sum(MODELS[m]["out"] for m in models) / len(models)
    avg_ji = sum(MODELS[j]["in"]  for j in judge_models) / len(judge_models)
    avg_jo = sum(MODELS[j]["out"] for j in judge_models) / len(judge_models)

    est_gen_tok_in, est_gen_tok_out = 400, 30
    est_jud_tok_in, est_jud_tok_out = 500, 80

    cost_gen  = n_gen  * (est_gen_tok_in * avg_gi + est_gen_tok_out * avg_go) / 1_000_000
    cost_eval = n_eval * (est_jud_tok_in * avg_ji + est_jud_tok_out * avg_jo) / 1_000_000
    cost_tot  = cost_gen + cost_eval

    est_sec = n_configs * 4 + n_eval * 2

    return (
        f"**{len(models)} мод x {len(active_prompts)} промпт x {n_outputs} выходов"
        f" = {n_gen} генераций | {n_gen} x {len(judge_models)} судей = {n_eval} оценок"
        f" | {total} вызовов**\n"
        f"~{fmt_cost(cost_tot)} | ~{est_sec} сек"
    )


# ── MAIN EXPERIMENT (generator) ───────────────────────────────────────────────

def run_experiment(models, prompts, temperature, n_outputs, judge_models, judge_prompt):
    active_prompts = [(i + 1, p) for i, p in enumerate(prompts) if p and p.strip()]

    if not models:
        yield {"status": "Выбери модели", "rows": [], "error": True}
        return
    if not active_prompts:
        yield {"status": "Заполни хотя бы один промпт", "rows": [], "error": True}
        return
    if not judge_models:
        yield {"status": "Выбери судью", "rows": [], "error": True}
        return

    configs = [
        {"model": m, "prompt_idx": idx, "prompt": p, "temperature": temperature}
        for m in models
        for idx, p in active_prompts
    ]

    n_configs = len(configs)
    n_outputs = int(n_outputs)

    # ── GENERATION ────────────────────────────────────────────────────────────
    yield {"status": f"Генерация: 0/{n_configs} конфигов...", "rows": [], "error": False}

    generated = []
    gen_cost = 0.0
    gen_done = 0

    def do_gen(cfg):
        r = call_model(cfg["model"], cfg["prompt"], cfg["temperature"])
        texts = []
        if not r["error"]:
            texts = [l.strip() for l in r["text"].strip().split("\n") if l.strip()][:n_outputs]
        return cfg, texts, r

    with ThreadPoolExecutor(max_workers=min(20, n_configs)) as ex:
        futures = [ex.submit(do_gen, cfg) for cfg in configs]
        for fut in as_completed(futures):
            cfg, texts, r = fut.result()
            generated.append((cfg, texts))
            gen_cost += r["cost_float"]
            gen_done += 1
            yield {
                "status": f"Генерация: {gen_done}/{n_configs} конфигов...",
                "rows": [], "error": False,
            }

    total_outputs = sum(len(texts) for _, texts in generated)

    # ── SCORING ───────────────────────────────────────────────────────────────
    score_tasks = [
        (cfg, text, judge)
        for cfg, texts in generated
        for text in texts
        for judge in judge_models
    ]
    n_eval    = len(score_tasks)
    eval_done = 0
    eval_cost = 0.0
    raw_rows  = []

    yield {"status": f"Скоринг: 0/{n_eval} оценок...", "rows": [], "error": False}

    def do_score(cfg, text, judge):
        score_input = f"{judge_prompt}\n\nText to evaluate:\n{text}"
        r = call_model(judge, score_input, 0.1)
        return cfg, text, judge, r

    with ThreadPoolExecutor(max_workers=min(30, max(n_eval, 1))) as ex:
        futures = [ex.submit(do_score, *t) for t in score_tasks]
        for fut in as_completed(futures):
            cfg, text, judge, r = fut.result()
            eval_cost += r["cost_float"]

            if r["error"]:
                scores = {"parse_error": r["error"], "overall": 0.0}
            else:
                scores = parse_judge_output(r["text"])

            row = {
                "model":       cfg["model"],
                "prompt_idx":  cfg["prompt_idx"],
                "temperature": cfg["temperature"],
                "judge":       judge,
                "output":      text,
                "output_short": text[:120] + ("..." if len(text) > 120 else ""),
            }
            row.update(scores)
            raw_rows.append(row)

            eval_done += 1
            if eval_done % 5 == 0 or eval_done == n_eval:
                yield {
                    "status": f"Скоринг: {eval_done}/{n_eval} оценок...",
                    "rows": [], "error": False,
                }

    # ── SAVE & FINALIZE ───────────────────────────────────────────────────────
    total_cost = gen_cost + eval_cost
    save_path  = _save_results(models, active_prompts, temperature, n_outputs,
                               judge_models, judge_prompt, raw_rows,
                               gen_cost, eval_cost)

    status = (
        f"Готово: {total_outputs} выходов, {n_eval} оценок | "
        f"{fmt_cost(total_cost)} | сохранено: {os.path.basename(save_path)}"
    )

    yield {"status": status, "rows": raw_rows, "error": False}


# ── AGGREGATION ───────────────────────────────────────────────────────────────

def build_dataframe(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # separate text and numeric judge columns
    base_cols = ["model", "prompt_idx", "temperature", "judge", "output_short"]
    judge_cols = [c for c in df.columns if c not in base_cols + ["output"]]
    text_judge = [c for c in judge_cols if df[c].dtype == object]
    num_judge  = [c for c in judge_cols
                  if c not in text_judge and c != "overall"]

    ordered = base_cols + text_judge + num_judge
    if "overall" in df.columns:
        ordered.append("overall")

    return df[[c for c in ordered if c in df.columns]].sort_values(
        "overall", ascending=False
    ).reset_index(drop=True)


def apply_filters(rows: list, filter_col: str, f_min: float, f_max: float,
                  filter_model: str, filter_prompt) -> pd.DataFrame:
    df = build_dataframe(rows)
    if df.empty:
        return df
    if filter_col and filter_col in df.columns:
        df = df[df[filter_col].between(f_min, f_max)]
    if filter_model and filter_model != "Все модели":
        df = df[df["model"] == filter_model]
    if filter_prompt and filter_prompt != "Все промпты":
        try:
            df = df[df["prompt_idx"] == int(str(filter_prompt).replace("Промпт ", ""))]
        except Exception:
            pass
    return df.reset_index(drop=True)


def get_numeric_cols(rows: list) -> list:
    if not rows:
        return ["overall"]
    df = pd.DataFrame(rows)
    skip = {"prompt_idx", "temperature"}
    return [c for c in df.columns
            if c not in skip and pd.api.types.is_numeric_dtype(df[c])]


# ── SAVE ──────────────────────────────────────────────────────────────────────

def _save_results(models, active_prompts, temperature, n_outputs,
                  judge_models, judge_prompt, raw_rows, gen_cost, eval_cost):
    fname = time.strftime("%Y%m%d_%H%M%S") + ".json"
    path  = os.path.join(RESULTS_DIR, fname)
    data  = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "models":       models,
            "prompts":      {str(idx): p for idx, p in active_prompts},
            "temperature":  temperature,
            "n_outputs":    n_outputs,
            "judge_models": judge_models,
            "judge_prompt": judge_prompt,
        },
        "stats": {
            "total_configs":     len(models) * len(active_prompts),
            "total_outputs":     sum(1 for r in raw_rows if r["judge"] == judge_models[0]),
            "total_evaluations": len(raw_rows),
            "gen_cost_usd":      round(gen_cost, 8),
            "eval_cost_usd":     round(eval_cost, 8),
            "total_cost_usd":    round(gen_cost + eval_cost, 8),
        },
        "rows": raw_rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path
