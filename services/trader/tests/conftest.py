import pytest, sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Point every test at a throwaway DB *before* trader modules are imported (the engine is created at import time).
# Tests delete rows, so they must never touch the dev or production database.
_tmpdir = tempfile.mkdtemp(prefix="trader-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["ALPACA_PAPER"] = "true"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
