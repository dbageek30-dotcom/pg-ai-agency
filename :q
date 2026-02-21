import requests
import json
import time

URL = "http://10.214.0.10:5050/plan_exec"
HEADERS = {"Authorization": "Bearer 123", "Content-Type": "application/json"}

def run_dba_test(question):
    print(f"\n🚀 QUESTION DBA : {question}")
    print("-" * 60)
    
    payload = {"question": question, "mode": "readonly"}
    start = time.time()
    
    try:
        r = requests.post(URL, json=payload, headers=HEADERS, timeout=180)
        duration = round(time.time() - start, 2)
        
        if r.status_code == 200:
            data = r.json()
            
            # --- AFFICHAGE DU RAISONNEMENT (Si ton planner le renvoie) ---
            print(f"🧠 RAISONNEMENT DE L'IA ({duration}s) :")
            # Si ton LLM est bavard, il met souvent ses pensées dans 'goal' ou un champ 'reasoning'
            print(f"   ∟ But identifié : {data.get('plan', {}).get('goal')}")
            
            print("\n📋 ÉTAPES PRÉVUES :")
            for i, step in enumerate(data.get('plan', {}).get('steps', []), 1):
                print(f"   {i}. [{step['tool']}] {step['intent']}")
                print(f"      Arguments: {step['args']}")

            # --- RÉSULTAT DE L'EXÉCUTION ---
            history = data.get("state", {}).get("history", [])
            print("\n⚙️ EXÉCUTION RÉELLE :")
            for h in history:
                status = "✅ SUCCESS" if h['result']['exit_code'] == 0 else "❌ FAILED"
                print(f"   ∟ {h['command']} -> {status}")
                if h['result'].get('stdout'):
                    print(f"      Sortie: {h['result']['stdout'].strip()}")

        else:
            print(f"❌ Erreur {r.status_code}: {r.text}")
            
    except Exception as e:
        print(f"💥 Erreur : {e}")

if __name__ == "__main__":
    # Test d'un outil spécifique Postgres
    run_dba_test("Vérifie si l'instance Postgres est prête à accepter des connexions")
