# security/safety.py
import re

# Patterns dangereux hors guillemets
DANGEROUS_PATTERNS = [
    r"\|",              # pipe
    r"&&",              # AND shell
    r"\|\|",            # OR shell
    r">",               # redirection
    r">>",              # redirection append
    r"\$\(.*\)",        # substitution de commande
    r"`.*`",            # backticks
    r"\brm\s+-rf\b",    # rm -rf
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bdd\b",
]

def strip_quoted(text: str) -> str:
    """
    Supprime le contenu entre guillemets simples ou doubles.
    Exemple :
        "psql -c 'SELECT 1;'" -> "psql -c ''"
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", text)

def is_safe(command: str) -> bool:
    """
    Vérifie si une commande est sûre.
    - On ignore les caractères dangereux dans les quotes
    - On bloque les patterns shell dangereux
    """
    cleaned = strip_quoted(command)

    # Bloquer les points-virgules hors quotes
    if ";" in cleaned:
        return False

    # Bloquer les autres patterns dangereux
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cleaned):
            return False

    return True

def get_unsafe_reason(command: str) -> str | None:
    cleaned = strip_quoted(command)

    if ";" in cleaned:
        return "Shell separator ';' detected outside quotes"

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cleaned):
            return f"Unsafe pattern detected: {pattern}"

    return None

