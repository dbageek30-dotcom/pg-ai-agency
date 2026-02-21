import json
import re
import logging
import os
import sys

from runtime.llm_client import MockLLM, OllamaClient
from runtime.discovery import load_config, get_registry
from security.allowlist import is_tool_allowed
from security.safety import is_safe

MAX_STEPS_PER_PLAN = 5
MAX_JSON_CHARS = 20000

def get_llm_client():
    cfg = load_config().get("llm", {})
    provider = cfg.get("provider", "mock")
    if provider == "ollama":
        return OllamaClient(
            url=cfg.get("url", "http://10.214.0.8:11434"),
            model=cfg.get("model", "qwen2.5:7b-instruct-q4_K_M")
        )
    return MockLLM()

def call_llm(prompt: str) -> str:
    ai = get_llm_client()
    return ai.chat(prompt)

def extract_json(raw: str) -> str:
    if not raw: raise ValueError("Empty response")
    cleaned = re.sub(r'```json\s*|\s*```', '', raw)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1: raise ValueError("No JSON found")
    return cleaned[start:end+1]

def build_planner_prompt(question, registry_binaries, tools_help, rag_context, pg_version, mode):
    docs_context = ""
    for name, help_text in tools_help.items():
        docs_context += f"--- LOCAL TOOL: {name} ---\n{help_text[:800]}\n\n"

    return f"""You are a PostgreSQL Expert Worker.
Respond ONLY in JSON.
PG_VERSION: {pg_version} | MODE: {mode}

QUESTION: "{question}"

OFFICIAL DOCUMENTATION (From Agency RAG):
{rag_context}

LOCAL BINARIES (Discovery):
{docs_context}

STRICT RULES:
1. If the OFFICIAL DOCUMENTATION describes a tool you don't have in LOCAL BINARIES, return "goal": "MISSING_TOOL: [name]" and empty steps [].
2. NEVER use 'ls' for system tasks. If 'df' is missing, report it.
"""

def validate_plan(plan: dict, registry_binaries: dict) -> dict:
    if "steps" not in plan: plan["steps"] = []
    safe_steps = []
    for step in plan["steps"]:
        tool = step.get("tool", "").split('/')[-1]
        if tool in registry_binaries and is_tool_allowed(tool):
            path = registry_binaries[tool]
            cmd = " ".join([str(path)] + [str(a) for a in step.get("args", [])])
            if is_safe(cmd):
                step["tool"] = tool
                safe_steps.append(step)
    plan["steps"] = safe_steps[:MAX_STEPS_PER_PLAN]
    return plan

def plan_actions(question, rag_context="No context provided", pg_version="unknown", mode="readonly"):
    # Plus besoin d'expert_rag ici ! On utilise le rag_context reçu par l'API
    registry_data = get_registry()
    registry_binaries = registry_data.get("binaries", {})
    rich_help = {t['name']: t.get('help_doc', 'No help') for t in registry_data.get("tools", [])}

    prompt = build_planner_prompt(question, registry_binaries, rich_help, rag_context, pg_version, mode)

    try:
        raw = call_llm(prompt)
        plan = json.loads(extract_json(raw))
        return validate_plan(plan, registry_binaries)
    except Exception as e:
        return {"goal": f"Error: {str(e)}", "steps": []}
