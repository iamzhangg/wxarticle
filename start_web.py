from __future__ import annotations
"""启动Web控制台"""
import sys
import os
from pathlib import Path

# Windows终端UTF-8
if sys.platform == "win32":
    os.system("")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn
from web_app import app

host = os.environ.get("HOST", "127.0.0.1")
port = int(os.environ.get("PORT", 8080))
print(f"🌐 wxarticle 控制台启动: http://{host}:{port}")
uvicorn.run(app, host=host, port=port, log_level="info")
