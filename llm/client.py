import os
import requests
from dotenv import load_dotenv

# Chargement du fichier .env situé à la racine du projet
load_dotenv()

class OllamaClient:
    def __init__(self):
        # Récupération stricte des variables d'environnement
        self.host = os.getenv("OLLAMA_HOST")
        self.port = os.getenv("OLLAMA_PORT", "11434")
        self.embed_model = os.getenv("EMBEDDING_MODEL")
        self.default_gen_model = os.getenv("GENERATION_MODEL")

        # Validation de la configuration
        if not self.host:
            raise EnvironmentError("OLLAMA_HOST is missing in .env file.")
        if not self.embed_model:
            raise EnvironmentError("EMBEDDING_MODEL is missing in .env file.")

        self.base_url = f"http://{self.host}:{self.port}/api"

    def get_embedding(self, text):
        """Generates a 768-dimension vector for the given text."""
        url = f"{self.base_url}/embeddings"
        payload = {
            "model": self.embed_model,
            "prompt": text
        }
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("embedding")
        
        except requests.exceptions.ConnectTimeout:
            print(f"❌ Error: Connection timeout to {self.host}. Is the VM up?")
        except requests.exceptions.HTTPError as e:
            print(f"❌ Error: Ollama returned an HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error: A network error occurred: {e}")
        return None

    def chat(self, user_prompt, context="", model=None):
        """Sends a prompt to the LLM with context and a technical system prompt."""
        target_model = model if model else self.default_gen_model
        url = f"{self.base_url}/chat"
        
        # English system prompt for better model alignment with technical docs
        system_content = (
            "You are a PostgreSQL expert specialized in server administration. "
            "Use the provided documentation context to answer the user's question accurately. "
            "If the answer is not in the context, state that you don't know based on the current docs. "
            "Maintain a professional and technical tone. "
            "Always provide SQL examples or configuration parameters when relevant."
        )
        
        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Context: {context}\n\nQuestion: {user_prompt}"}
            ],
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120) # Timeout plus long pour la génération
            response.raise_for_status()
            return response.json()["message"]["content"]
        
        except Exception as e:
            return f"⚠️ Error during LLM generation: {str(e)}"

# Petit test rapide si exécuté directement
if __name__ == "__main__":
    try:
        client = OllamaClient()
        print(f"✅ Client initialized for {client.base_url}")
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
