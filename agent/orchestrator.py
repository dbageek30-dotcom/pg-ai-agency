# agent/orchestrator.py
import time
import logging

from executor import run_command
from security.allowlist import is_tool_allowed
from security.safety import is_safe
from runtime.audit import log_execution

MAX_PLAN_DURATION = 60  # secondes


def build_command(tool, args, registry):
    """
    Construit la commande finale à partir du tool logique et du registry.
    """
    path = registry.get(tool, tool)
    return " ".join([path] + args)


def run_plan(plan, registry):
    """
    Exécute un plan validé, étape par étape, avec garde-fous.
    Retourne un state contenant l'historique et les erreurs.
    """
    state = {
        "history": [],
        "errors": [],
        "start_time": time.time()
    }

    for i, step in enumerate(plan.get("steps", [])):
        if i >= plan.get("max_steps", 3):
            break

        if time.time() - state["start_time"] > MAX_PLAN_DURATION:
            state["errors"].append("Plan aborted: timeout")
            break

        tool = step.get("tool")
        args = step.get("args", [])

        if not tool:
            state["errors"].append("Missing tool in step")
            if step.get("on_error") == "abort":
                break
            continue

        if not is_tool_allowed(tool):
            msg = f"Tool not allowed: {tool}"
            logging.warning(msg)
            state["errors"].append(msg)
            if step.get("on_error") == "abort":
                break
            continue

        cmd = build_command(tool, args, registry)

        if not is_safe(cmd):
            msg = f"Unsafe command: {cmd}"
            logging.warning(msg)
            state["errors"].append(msg)
            if step.get("on_error") == "abort":
                break
            continue

        logging.info(f"[PLAN-STEP] Executing: {cmd}")
        result = run_command(cmd)

        # Audit
        try:
            log_execution(
                command=cmd,
                executed_command=result.get("command_executed", cmd),
                exit_code=result.get("exit_code", -1),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", "")
            )
        except Exception as e:
            logging.error(f"Audit log failed in plan: {e}")

        state["history"].append({
            "step": step,
            "command": cmd,
            "result": result
        })

        if result.get("exit_code", 1) != 0 and step.get("on_error") == "abort":
            break

    return state

