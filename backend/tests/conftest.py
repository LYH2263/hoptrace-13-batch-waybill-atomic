import os
import tempfile
from pathlib import Path

# 必须在导入 app 之前固定数据目录（app.db 在导入时定型）
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hoptrace-test-"))
os.environ.setdefault("FIXTURES_DIR", str(Path(__file__).resolve().parents[2] / "fixtures"))
