import subprocess
import shlex

def run_command(command: str) -> dict:
    """
    Exécute une commande locale et renvoie stdout/stderr/exit_code.
    Sécurisé : pas de shell=True.
    """
    try:
        process = subprocess.Popen(
            shlex.split(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate()

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1
        }

