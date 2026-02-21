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
    # On construit la documentation à partir de tools_help (dict: tool_name -> help_text)
    docs_context = ""
    if isinstance(tools_help, dict):
        for tool_name, help_text in tools_help.items():
            docs_context += f"--- TOOL: {tool_name} ---\n{help_text[:1000]}\n\n"
    else:
        docs_context = "No detailed documentation available. Use tool names only."

    return f"""You are a PostgreSQL DBA Expert. Respond ONLY in JSON.
Question: "{question}"
Available tools: {list(registry_binaries.keys())}
PG Version: {pg_version} | Mode: {mode}

DOCUMENTATION (The only actions allowed are those described here):
{docs_context}

STRICT RULES:
1. READ THE DOCS: Only use a tool if its documentation explicitly confirms it can do the task.
2. MISSING TOOL: If no tool covers the request (e.g. "check disk space" requires 'df'), return "steps": [] and set the goal to "MISSING_TOOL: I need [tool_name] because [reason]".
3. NO GUESSING: Never use 'ls' or 'psql' for tasks they are not designed for.
4. JUSTIFY: Provide a justification for each step based on the manual.

EXPECTED JSON SCHEMA:
{{
  "goal": "Description or MISSING_TOOL request",
  "steps": [
    {{
      "tool": "...", "args": ["..."], "justification": "...", "intent": "..."
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

        tool_path = registry_binaries[actual_tool_key]
        cmd = " ".join([str(tool_path)] + [str(a) for a in args])

        if not is_safe(cmd):
            continue

        step["tool"] = actual_tool_key
        step["on_error"] = step.get("on_error", "abort")
        safe_steps.append(step)

    plan["steps"] = safe_steps[:plan["max_steps"]]
    return plan

def plan_actions(question, tools_help=None, pg_version="unknown", mode="readonly"):
    # On récupère le registry complet du discovery
    registry_data = get_registry()
    registry_binaries = registry_data.get("binaries", {})
    
    # Si tools_help n'est pas fourni ou est une liste, on le reconstruit depuis le discovery
    # pour avoir le dictionnaire {nom: help_doc}
    rich_help = {}
    for tool_entry in registry_data.get("tools", []):
        rich_help[tool_entry['name']] = tool_entry.get('help_doc', 'No help available')

    prompt = build_planner_prompt(
        question=question,
        registry_binaries=registry_binaries,
        tools_help=rich_help,
        pg_version=pg_version,
        mode=mode
    )

    try:
        raw_llm_output = call_llm(prompt)
        json_str = extract_json(raw_llm_output)
        plan = json.loads(json_str)
        return validate_plan(plan, registry_binaries)
    except Exception as e:
        return {"goal": f"Error: {str(e)}", "steps": []}
