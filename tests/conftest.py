import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated data dir and harmless settings for tests. Must happen before server.config is imported.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="projectbilal-test-"))
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("META_APP_SECRET", "test-secret")
os.environ.setdefault("META_VERIFY_TOKEN", "verify-me")
os.environ.setdefault("APPROVAL_SECRET", "approval-secret")
os.environ.setdefault("PUBLIC_DOMAIN", "example.test")
os.environ.setdefault("MAIL_ADDRESS", "assistant@example.test")
