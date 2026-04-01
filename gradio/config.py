import os

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

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(PROMPTS_DIR, exist_ok=True)

DEFAULT_N_OUTPUTS   = 15
DEFAULT_TEMPERATURE = 0.7
MAX_PROMPT_SLOTS    = 5
API_TIMEOUT         = 45

DEFAULT_PROMPT = """You are a B2B cold email expert. Write 15 unique, personalized cold email icebreakers for this lead. Output ONLY the icebreakers, one per line, no numbering, no bullets.

Lead:
Name: Alex Rodriguez
Title: Director of Revenue Operations
Company: GrowthStack
Industry: B2B SaaS
LinkedIn: Just hired 3 new RevOps analysts. Scaling fast!"""

DEFAULT_JUDGE_PROMPT = """You are an expert evaluator of cold email icebreakers.

Score the following icebreaker on these criteria (1-10 each):
- personalization: how specific and tailored to this lead
- tone: natural, not salesy, conversational
- hook: unique angle, sparks curiosity

Respond ONLY with valid JSON, no explanation outside JSON:
{"personalization": 8, "tone": 9, "hook": 7, "verdict": "Strong hook but could be more specific"}"""
