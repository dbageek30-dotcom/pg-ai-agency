import pytest
import os
import json
from unittest.mock import patch, MagicMock
from runtime.discovery import get_version_from_path, discover_binaries

# 1. Tests unitaires sur la Regex de versioning
@pytest.mark.parametrize("path, expected", [
    ("/usr/lib/postgresql/16/bin", "16"),
    ("/usr/pgsql-13/bin", "13"),
    ("/opt/postgresql-9.6/bin", "9.6"),
    ("/usr/bin", None),
    ("/custom/path/no-version/bin", None),
])
def test_get_version_from_path(path, expected):
    assert get_version_from_path(path) == expected

# 2. Test d'intégration (Simulation du système de fichiers)
def test_discover_binaries_mocked():
    """Vérifie la logique de tri et d'aliasing avec des dossiers fictifs."""
    
    mock_dirs = [
        "/usr/lib/postgresql/12/bin",
        "/usr/lib/postgresql/16/bin"
    ]
    
    def mock_scandir(path):
        # Création de l'entrée mockée
        mock_entry = MagicMock()
        mock_entry.name = "psql"
        mock_entry.path = os.path.join(path, "psql")
        mock_entry.is_file.return_value = True
        
        # On simule le comportement du context manager (__enter__)
        # qui doit retourner un itérable
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = [mock_entry]
        return mock_cm

    with patch("glob.glob", return_value=mock_dirs), \
         patch("os.path.isdir", return_value=True), \
         patch("os.access", return_value=True), \
         patch("os.scandir", side_effect=mock_scandir), \
         patch("runtime.discovery.discover_pg_extensions", return_value={"pgvector": "0.5.0"}):
        
        registry = discover_binaries()
        
        # psql (alias principal) doit pointer vers la version 16 (tri descendant)
        assert "psql" in registry["binaries"]
        assert "16" in registry["binaries"]["psql"]
        
        # Vérification des alias versionnés
        assert "psql-16" in registry["binaries"]
        assert "psql-12" in registry["binaries"]
        
        # Vérification des capacités
        assert registry["capabilities"]["extensions"]["pgvector"] == "0.5.0"

# 3. Test de sécurité : s'assurer que le scan ne crash pas sur un dossier interdit
def test_discovery_permission_resilience():
    with patch("os.scandir", side_effect=PermissionError):
        # Ne doit pas lever d'exception
        registry = discover_binaries()
        assert isinstance(registry, dict)
        assert "binaries" in registry
