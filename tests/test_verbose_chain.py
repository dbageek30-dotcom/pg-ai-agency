import requests
import json
import time

# Configuration
AGENT_URL = "http://10.214.0.10:5050"
HEADERS = {"Authorization": "Bearer 123", "Content-Type": "application/json"}

def log_step(step_name, status="...", details=""):
    """Formatage propre des étapes dans la console"""
    symbol = "⏳" if status == "..." else ("✅" if status == "OK" else "❌")
    print(f"{symbol} {step_name:<30} [{status}] {details}")

def run_verbose_test():
    print(f"\n{'='*60}")
    print(f"🔬 DIAGNOSTIC COMPLET DE LA CHAÎNE PG-AGENT")
    print(f"{'='*60}\n")

    # --- ÉTAPE 1: Connexion Réseau ---
    try:
        r_health = requests.get(f"{AGENT_URL}/health", timeout=5)
        if r_health.status_code == 200:
            log_step("Connexion Réseau (Health)", "OK", f"v{r_health.json().get('version')}")
        else:
            log_step("Connexion Réseau (Health)", "FAIL", f"HTTP {r_health.status_code}")
            return
    except Exception as e:
        log_step("Connexion Réseau (Health)", "FAIL", str(e))
        return

    # --- ÉTAPE 2: Discovery & Registry ---
    try:
        r_reg = requests.get(f"{AGENT_URL}/registry", headers=HEADERS, timeout=5)
        reg_data = r_reg.json()
        if r_reg.status_code == 200:
            num_tools = len(reg_data.get('tools', []))
            log_step("Discovery (Registry)", "OK", f"{num_tools} outils trouvés")
        else:
            log_step("Discovery (Registry)", "FAIL", r_reg.text)
    except Exception as e:
        log_step("Discovery (Registry)", "FAIL", str(e))

    # --- ÉTAPE 3: Planning & Orchestration (Le gros test) ---
    log_step("Envoi Question (Plan_Exec)", "...")
    payload = {"question": "run ls", "mode": "readonly"}
    
    start_time = time.time()
    try:
        r_plan = requests.post(f"{AGENT_URL}/plan_exec", json=payload, headers=HEADERS, timeout=180)
        duration = round(time.time() - start_time, 2)

        if r_plan.status_code == 409:
            log_step("Planning LLM", "FAIL", "CONFLIT de versions détecté (Arbitrage requis)")
            print(f"   ∟ Détails: {json.dumps(r_plan.json().get('details'), indent=7)}")
            return

        if r_plan.status_code == 200:
            data = r_plan.json()
            log_step("Planning LLM", "OK", f"Réponse en {duration}s")
            
            # --- ÉTAPE 4: Validation de l'Exécution ---
            history = data.get("state", {}).get("history", [])
            if history:
                last_step = history[-1]
                cmd = last_step.get("command")
                exit_code = last_step.get("result", {}).get("exit_code")
                
                status_exec = "OK" if exit_code == 0 else "FAIL"
                log_step("Exécution (Bwrap/Shell)", status_exec, f"Code: {exit_code}")
                print(f"   ∟ Commande résolue: {cmd}")
                
                if exit_code != 0:
                    print(f"   ∟ Erreur: {last_step.get('result', {}).get('stderr')}")
            else:
                log_step("Exécution", "FAIL", "Le plan n'a généré aucune étape d'exécution")
        else:
            log_step("Planning LLM", "FAIL", f"HTTP {r_plan.status_code} - {r_plan.text}")

    except Exception as e:
        log_step("Planning LLM", "FAIL", str(e))

    print(f"\n{'='*60}")
    print(f"🏁 FIN DU DIAGNOSTIC")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_verbose_test()
