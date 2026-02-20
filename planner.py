import json
import re
from llm.client import call_llm
from security.allowlist import is_tool_allowed
from security.safety import is_safe
from runtime.registry import get_registry

# Limites globales (production-grade)
MAX_STEPS_PER_PLAN = 5
MAX_JSON_CHARS = 20000


# ------------------------------------------------------------
# Extraction robuste du JSON renvoyé par le LLM
# ------------------------------------------------------------
def extract_json(raw: str) -> str:
    """
    Extrait le premier bloc JSON valide dans une réponse LLM.
    Tolère du texte autour, des explications, etc.
    """
    if not raw:
        raise ValueError("Empty LLM response")

    # Cherche le premier '{' et le dernier '}'
    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")

    json_str = raw[start:end + 1]

    if len(json_str) > MAX_JSON_CHARS:
        raise ValueError("JSON too large")

    return json_str


# ------------------------------------------------------------
# Prompt du planner
# ------------------------------------------------------------
def build_planner_prompt(question, registry, tools_help, pg_version, mode="readonly"):
    return f"""
You are a PostgreSQL DBA assistant. You NEVER execute commands.
You ONLY return a JSON plan that will be validated and executed by a secure agent.

User question:
{question}

PostgreSQL version: {pg_version}
Execution mode: {mode}

Available tools:
{json.dumps(tools_help, indent=2)}

You MUST respond with a single JSON object with this schema:
{{
  "goal": "short description",
  "mode": "readonly | maintenance | change",
  "max_steps": integer <= {MAX_STEPS_PER_PLAN},
  "steps": [
    {{
      "id": "short_id",
      "tool": "tool_name",
      "args": ["arg1", "arg2"],
      "intent": "what this step does",
      "on_error": "abort" or "continue"
    }}
  ]
}}

Rules:
- NEVER include destructive commands (DROP, DELETE, TRUNCATE, rm, etc.).
- Use only tools listed above.
- Prefer read-only operations in mode=readonly.
- If no action is needed, return max_steps=0 and steps=[].
"""


# ------------------------------------------------------------
# Validation stricte du plan
# ------------------------------------------------------------
def validate_plan(plan: dict, registry: dict) -> dict:
    """
    Valide et nettoie un plan JSON proposé par le LLM.
    Applique toutes les règles de sécurité.
    """
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a JSON object")

    if "steps" not in plan or "max_steps" not in plan:
        raise ValueError("Invalid plan: missing keys")

    if not isinstance(plan["steps"], list):
        raise ValueError("Invalid plan: steps must be a list")

    # Limite stricte
    plan["max_steps"] = min(plan.get("max_steps", 0), MAX_STEPS_PER_PLAN)

    # Mode d'exécution
    mode = plan.get("mode", "readonly")
    if mode not in ["readonly", "maintenance", "change"]:
        mode = "readonly"
    plan["mode"] = mode

    safe_steps = []

    for step in plan["steps"]:
        tool = step.get("tool")
        args = step.get("args", [])

        if not tool or not isinstance(args, list):
            continue

        # Vérification allowlist
        if not is_tool_allowed(tool):
            continue

        # Construction commande
        tool_path = registry.get(tool, tool)
        cmd = " ".join([tool_path] + args)

        # Mode readonly = stricte lecture
        if mode == "readonly" and not is_safe(cmd, readonly_strict=True):
            continue

        # Vérification sécurité globale
        if not is_safe(cmd):
            continue

        # Normalisation on_error
        step["on_error"] = step.get("on_error", "abort")
        if step["on_error"] not in ["abort", "continue"]:
            step["on_error"] = "abort"

        safe_steps.append(step)

    plan["steps"] = safe_steps[:plan["max_steps"]]
    return plan


# ------------------------------------------------------------
# Fonction principale : génère un plan validé
# ------------------------------------------------------------
def plan_actions(question, tools_help, pg_version="unknown", mode="readonly"):
    """
    Génère un plan JSON validé et sécurisé.
    """
    registry = get_registry()

    prompt = build_planner_prompt(
        question=question,
        registry=registry,
        tools_help=tools_help,
        pg_version=pg_version,
        mode=mode
    )

    raw = call_llm(prompt)
    json_str = extract_json(raw)
    plan = json.loads(json_str)

    return validate_plan(plan, registry)

