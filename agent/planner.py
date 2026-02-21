import json
import re
import logging
import os
import sys

# Import de ton moteur RAG Expert
from agency_expert import DBAgencyExpert
from runtime.llm_client import MockLLM, OllamaClient
from runtime.discovery import load_config, get_registry
from security.allowlist import is_tool_allowed
from security.safety import is_safe

MAX_STEPS_PER_PLAN = 5
MAX_JSON_CHARS = 20000

# Initialisation de l'expert RAG (une seule fois pour charger le reranker CPU)
expert_rag = DBAgencyExpert()

def get_llm_client():
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
    if not raw: raise ValueError("Empty LLM response")
    cleaned = re.sub(r'```json\s*|\s*```', '', raw)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1: raise ValueError("No JSON found")
    return cleaned[start:end + 1]

def build_planner_prompt(question, registry_binaries, tools_help, rag_context, pg_version, mode):
    # Fusion du manuel local (Discovery) et de la doc officielle (RAG)
    docs_context = ""
    for tool_name, help_text in tools_help.items():
        docs_context += f"--- LOCAL TOOL: {tool_name} ---\n{help_text[:800]}\n\n"

    return f"""You are the PostgreSQL Expert Worker. A DBAManager has assigned you this task.
Respond ONLY in JSON.

QUESTION: "{question}"
PG_VERSION: {pg_version} | MODE: {mode}

OFFICIAL DOCUMENTATION (RAG):
{rag_context}

LOCAL TOOLS CAPABILITIES (DISCOVERY):
{docs_context}

STRICT WORKER RULES:
1. DOCUMENTATION FIRST: Check if the OFFICIAL DOCUMENTATION describes a procedure for this task.
2. TOOL MATCH: Only use a tool if the procedure in the RAG matches the LOCAL TOOL manual.
3. ABORT ON SYSTEM TASKS: If the RAG or tools do not cover the task (e.g. "disk space"), return "steps": [] and "goal": "MISSING_TOOL: [name]".
4. NO SUBSTITUTION: Never use 'ls' to approximate 'df'. Never use SQL to guess OS metrics.
"""

def validate_plan(plan: dict, registry_binaries: dict) -> dict:
    # (Logique de validation identique pour garantir la sécurité bwrap)
    if "steps" not in plan: plan["steps"] = []
    safe_steps = []
    for step in plan["steps"]:
        tool = step.get("tool", "").split('/')[-1]
        if tool in registry_binaries and is_tool_allowed(tool):
            tool_path = registry_binaries[tool]
            cmd = " ".join([str(tool_path)] + [str(a) for a in step.get("args", [])])
            if is_safe(cmd):
                step["tool"] = tool
                safe_steps.append(step)
    plan["steps"] = safe_steps[:MAX_STEPS_PER_PLAN]
    return plan

def plan_actions(question, tools_help=None, pg_version="unknown", mode="readonly"):
    # 1. RÉCUPÉRATION DU CONTEXTE OFFICIEL (RAG + Reranker)
    # On utilise ton expert pour obtenir la "vérité" documentaire
    print(f"🛠️  Consultation du RAG pour l'Expert PostgreSQL...")
    rag_context = expert_rag.ask(question)

    # 2. RÉCUPÉRATION DE L'INVENTAIRE LOCAL
    registry_data = get_registry()
    registry_binaries = registry_data.get("binaries", {})
    
    rich_help = {t['name']: t.get('help_doc', 'No help') for t in registry_data.get("tools", [])}

    # 3. GÉNÉRATION DU PLAN
    prompt = build_planner_prompt(
        question=question,
        registry_binaries=registry_binaries,
        tools_help=rich_help,
        rag_context=rag_context,
        pg_version=pg_version,
        mode=mode
    )

    try:
        raw_llm_output = call_llm(prompt)
        plan = json.loads(extract_json(raw_llm_output))
        return validate_plan(plan, registry_binaries)
    except Exception as e:
        return {"goal": f"Error: {str(e)}", "steps": []}
