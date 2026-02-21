import json
import requests
import re

class BaseLLMClient:
    def chat(self, prompt: str, model: str | None = None) -> str:
        raise NotImplementedError

class MockLLM(BaseLLMClient):
    def chat(self, prompt: str, model: str | None = None) -> str:
        # Simule une réponse instantanée et valide
        return json.dumps({
            "goal": "Vérification des sauvegardes (Mode Mock)",
            "mode": "readonly",
            "max_steps": 1,
            "steps": [
                {
                    "id": "check_pg_data",
                    "tool": "ls",
                    "args": ["-lh", "/var/lib/postgresql"],
                    "intent": "Lister le contenu pour diagnostic",
                    "on_error": "continue"
                }
            ]
        })

class OllamaClient(BaseLLMClient):
    def __init__(self, url: str, model: str):
        self.url = url
        self.model = model

    def chat(self, prompt: str, model: str | None = None) -> str:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        try:
            # Timeout de 180s pour les CPU lents
            r = requests.post(f"{self.url}/api/generate", json=payload, timeout=1800)
            r.raise_for_status()
            response_data = r.json().get("response", "")
            
            # Nettoyage si le modèle renvoie des balises Markdown
            cleaned = re.sub(r'```json\s*', '', response_data)
            cleaned = re.sub(r'\s*```', '', cleaned)
            return cleaned.strip()
        except Exception as e:
            return json.dumps({"error": f"LLM Connection Error: {str(e)}"})
