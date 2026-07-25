import os
import sys
import tempfile
from pathlib import Path


TEST_ROOT = tempfile.mkdtemp(prefix="sumkora-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DB_PATH"] = os.path.join(TEST_ROOT, "test.db")
os.environ["UPLOAD_DIR"] = os.path.join(TEST_ROOT, "uploads")
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-sessions"
os.environ["OCR_ENABLED"] = "false"
os.environ["CXSEE_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["COOKIE_SECURE"] = "false"
