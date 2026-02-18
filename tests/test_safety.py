# tests/test_safety.py
from agent.security.safety import is_safe, get_unsafe_reason

def test_safe_commands():
    assert is_safe("pgbackrest info")
    assert is_safe("psql -c 'SELECT 1;'")
    assert is_safe("patroni --version")

def test_unsafe_pipes():
    assert not is_safe("pgbackrest info | grep error")

def test_unsafe_semicolon():
    assert not is_safe("psql -c 'SELECT 1;' ; rm -rf /")

def test_unsafe_redirection():
    assert not is_safe("pgbackrest info > /tmp/out.txt")

def test_unsafe_subshell():
    assert not is_safe("psql -c $(cat /etc/passwd)")

def test_unsafe_backticks():
    assert not is_safe("psql -c `cat /etc/passwd`")

def test_rm_rf():
    assert not is_safe("rm -rf /")

def test_reason():
    reason = get_unsafe_reason("rm -rf /")
    assert reason is not None
    assert "rm" in reason.lower()

