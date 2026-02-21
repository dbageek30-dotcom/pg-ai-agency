import requests
import json
import time

URL = "http://10.214.0.10:5050/plan_exec"
HEADERS = {"Authorization": "Bearer 123", "Content-Type": "application/json"}

def test_run_diagnostic():
    # Question technique en anglais
    question = "Check if the PostgreSQL instance is ready to accept connections"
    
    print(f"\n🔍 [QUERY]: {question}")
    print("="*60)
    
    try:
        start_time = time.time()
        r = requests.post(URL, json={"question": question, "mode": "readonly"}, headers=HEADERS)
        duration = round(time.time() - start_time, 2)
        
        if r.status_code == 200:
            res = r.json()
            plan = res.get("plan", {})
            
            # --- 1. LE RAISONNEMENT (GOAL) ---
            print(f"\n🧠 [LLM REASONING - {duration}s]")
            print(f"Goal: {plan.get('goal', 'No goal defined')}")
            
            # --- 2. LE PLAN DÉTAILLÉ ---
            print("\n📋 [STRATEGY]")
            for i, step in enumerate(plan.get("steps", []), 1):
                print(f"  Step {i}: Using tool '{step['tool']}'")
                print(f"  Intent: {step['intent']}")
                print(f"  Arguments: {step['args']}")
            
            # --- 3. RÉSULTAT TECHNIQUE ---
            print("\n⚙️ [EXECUTION LOGS]")
            history = res.get("state", {}).get("history", [])
            if history:
                for h in history:
                    cmd = h.get("command")
                    out = h.get("result", {}).get("stdout", "").strip()
                    err = h.get("result", {}).get("stderr", "").strip()
                    code = h.get("result", {}).get("exit_code")
                    
                    status = "✅" if code == 0 else "❌"
                    print(f"  {status} Command: {cmd}")
                    if out: print(f"     Output: {out}")
                    if err: print(f"     Error: {err}")
            else:
                print("  ⚠️ No steps were executed.")
                
        else:
            print(f"❌ Server Error: {r.status_code}")
            print(r.text)

    except Exception as e:
        print(f"💥 Connection Error: {e}")

if __name__ == "__main__":
    test_run_diagnostic()
