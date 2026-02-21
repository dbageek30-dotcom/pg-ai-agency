import json
import re
import logging
from runtime.llm_client import MockLLM, OllamaClient
from runtime.discovery import load_config, get_registry
from security.allowlist import is_tool_allowed
from security.safety import is_safe

MAX_STEPS_PER_PLAN = 5
MAX_JSON_CHARS = 20000

def get_llm_client():
    """Fabrique locale pour éviter les imports circulaires avec discovery."""
    cfg = load_config().get("llm", {})
    provider = cfg.get("provider", "mock")

    if provider == "ollama":
        return OllamaClient(
            url=cfg.get("url", "http://10.214.0.8:11434"),
            model=cfg.get("model", "qwen2.5:7b-instruct-q4_K_M")
        )
    return MockLLM()

def call_llm(prompt: str, model: str | None = None) -> str:
    ai = get_llm_client()
    return ai.chat(prompt, model=model)

def extract_json(raw: str) -> str:
    if not raw:
        raise ValueError("Empty LLM response")

    cleaned = re.sub(r'```json\s*', '', raw)
    cleaned = re.sub(r'\s*```', '', cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found. Raw: {raw[:100]}")

    json_str = cleaned[start:end + 1]
    if len(json_str) > MAX_JSON_CHARS:
        raise ValueError("JSON too large")

    return json_str

def build_planner_prompt(question, registry_binaries, tools_help, pg_version, mode="readonly"):
    tools_list = list(registry_binaries.keys())
    
    return f"""You are a PostgreSQL DBA Expert. Respond ONLY in JSON.
User question: "{question}"
PG Version: {pg_version} | Mode: {mode}
Available tools: {tools_list}

RULES:
1. CONSULT: Review available tools. If NO tool can perform the task, return an empty steps list and explain in the "goal".
2. UNCERTAINTY: If you are unsure of a tool's syntax, your first step MUST be to use 'tool --help'.
3. ACCURACY: DO NOT misuse tools (e.g., do not use 'psql' to run bash commands like 'tail').
4. JUSTIFY: For each step, provide a "justification" and a "risk_assessment".

EXPECTED JSON SCHEMA:
{{
  "goal": "Explain what you will do OR why it's impossible with available tools",
  "mode": "{mode}",
  "max_steps": {MAX_STEPS_PER_PLAN},
  "steps": [
    {{
      "id": "step_1",
      "tool": "tool_name",
      "args": ["--help"],
      "justification": "I need to verify the exact flags to avoid syntax errors.",
      "risk_assessment": "low",
      "intent": "Read manual",
      "on_error": "abort"
    }}
  ]
}}
"""

def validate_plan(plan: dict, registry_binaries: dict) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a JSON object")

    if "steps" not in plan:
        plan["steps"] = []
    
    plan["max_steps"] = min(plan.get("max_steps", 0) or 5, MAX_STEPS_PER_PLAN)
    safe_steps = []

    for step in plan["steps"]:
        tool = step.get("tool", "")
        args = step.get("args", [])

        if not tool or not isinstance(args, list):
            continue

        clean_name = tool.split('/')[-1]
        actual_tool_key = None

        if clean_name in registry_binaries:
            actual_tool_key = clean_name
        else:
            for k in registry_binaries.keys():
                if k.startswith(clean_name):
                    actual_tool_key = k
                    break

        if not actual_tool_key:
            continue

        if not is_tool_allowed(actual_tool_key) and not is_tool_allowed(clean_name):
            continue

        # Résolution du chemin pour Bubblewrap
        tool_path = registry_binaries[actual_tool_key]
        cmd = " ".join([str(tool_path)] + [str(a) for a in args])

        if not is_safe(cmd):
            continue

        step["tool"] = actual_tool_key
        step["on_error"] = step.get("on_error", "abort")
        safe_steps.append(step)

    plan["steps"] = safe_steps[:plan["max_steps"]]
    return plan

def plan_actions(question, tools_help, pg_version="unknown", mode="readonly"):
    registry_data = get_registry()
    registry_binaries = registry_data.get("binaries", {})

    prompt = build_planner_prompt(
        question=question,
        registry_binaries=registry_binaries,
        tools_help=tools_help,
        pg_version=pg_version,
        mode=mode
    )

    raw_llm_output = call_llm(prompt)
    json_str = extract_json(raw_llm_output)
    plan = json.loads(json_str)

    return validate_plan(plan, registry_binaries)
