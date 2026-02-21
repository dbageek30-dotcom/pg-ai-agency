# agent/orchestrator.py
import time
import logging

from executor import run_command
from security.allowlist import is_tool_allowed
from security.safety import is_safe
from runtime.audit import log_execution

MAX_PLAN_DURATION = 60  # secondes

def build_command(tool, args, binaries_registry):
    """
    Construit la commande finale à partir du tool logique et de la map des binaires.
    Le binaries_registry est le dictionnaire 'binaries' du registry.json.
    """
    # On cherche le chemin absolu résolu par discovery.py
    # Si non trouvé (ex: 'ls'), on garde le nom tel quel.
    path = binaries_registry.get(tool, tool)
    
    # Construction de la ligne de commande
    return " ".join([path] + [str(a) for a in args])

def run_plan(plan, binaries_registry):
    """
    Exécute un plan validé, étape par étape, avec garde-fous.
    """
    state = {
        "history": [],
        "errors": [],
        "start_time": time.time()
    }

    # Le registre passé ici est registry["binaries"]
    for i, step in enumerate(plan.get("steps", [])):
        # Limitation du nombre d'étapes
        if i >= plan.get("max_steps", 5):
            break

        # Check Timeout Global
        if time.time() - state["start_time"] > MAX_PLAN_DURATION:
            state["errors"].append("Plan aborted: timeout")
            break

        tool = step.get("tool")
        args = step.get("args", [])

        if not tool:
            state["errors"].append("Missing tool in step")
            if step.get("on_error") == "abort": break
            continue

        # 1. Validation de la allowlist (toujours par précaution)
        if not is_tool_allowed(tool):
            msg = f"Tool not allowed: {tool}"
            logging.warning(msg)
            state["errors"].append(msg)
            if step.get("on_error") == "abort": break
            continue

        # 2. Résolution du chemin et construction
        cmd = build_command(tool, args, binaries_registry)

        # 3. Validation Safety (Check injections, etc.)
        if not is_safe(cmd):
            msg = f"Unsafe command blocked by safety engine: {cmd}"
            logging.warning(msg)
            state["errors"].append(msg)
            if step.get("on_error") == "abort": break
            continue

        logging.info(f"[PLAN-STEP] Executing: {cmd}")
        
        # 4. Exécution réelle
        result = run_command(cmd)

        # Audit System
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

        # Historique pour le client
        state["history"].append({
            "step": step,
            "command": cmd,
            "result": result
        })

        # Gestion des erreurs d'exécution
        if result.get("exit_code", 0) != 0:
            if step.get("on_error") == "abort":
                state["errors"].append(f"Step {i} failed, aborting plan.")
                break

    return state
