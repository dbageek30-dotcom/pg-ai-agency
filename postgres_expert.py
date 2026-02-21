import os
import requests
from agency_expert import DBAgencyExpert

class PostgresExpertManager:
    def __init__(self, agent_url, api_token):
        self.rag_expert = DBAgencyExpert()
        self.agent_url = agent_url
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def resolve_and_execute(self, question):
        # 1. On récupère la doc officielle via ton RAG + Reranker
        print(f"🔍 [Agency] Recherche RAG pour : {question}")
        rag_context = self.rag_expert.ask(question)

        # 2. On envoie tout au Planner de la VM-PG
        payload = {
            "question": question,
            "rag_context": rag_context  # On injecte la doc ici
        }

        print(f"📡 [Agency] Envoi du contexte à la VM-PG...")
        response = requests.post(f"{self.agent_url}/plan_exec", json=payload, headers=self.headers)
        return response.json()

if __name__ == "__main__":
    # Test rapide
    AGENT_IP = "10.214.0.10" # IP de ta VM-PG
    manager = PostgresExpertManager(f"http://{AGENT_IP}:5050", "123")
    result = manager.resolve_and_execute("Check available disk space")
    print(result)
