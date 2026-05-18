"""
kroniqo-ui/api_server.py
Lightweight HTTP server that exposes Kroniqo's biography and decisions
for the web UI dashboard. Run alongside agent.py.

Usage:
  python kroniqo-ui/api_server.py

Opens: http://localhost:7842
"""

import sys
import os
import json
import sqlite3
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / 'kroniqo-core'))
from consequence_graph import get_biography

DB_PATH = Path(__file__).parent.parent / 'kroniqo-core' / 'kroniqo.db'
UI_DIR  = Path(__file__).parent
PORT    = 7842

# Load .env
_env = Path(__file__).parent.parent / '.env'
if _env.exists():
    for line in _env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_decisions(limit: int = 50) -> list:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, timestamp, domain, task, confidence_expressed, outcome, magnitude, notes
        FROM consequences
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


class KroniqoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/biography':
            self._json(get_biography())

        elif parsed.path == '/api/decisions':
            self._json(get_decisions())

        elif parsed.path == '/api/status':
            bio = get_biography()
            self._json({
                "age": bio["age"],
                "domains": len(bio.get("domains", {})),
                "backend": os.environ.get("GROQ_API_KEY") and "groq" or
                           os.environ.get("GEMINI_API_KEY") and "gemini" or "unknown",
                "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            })

        else:
            # Serve static files (index.html etc)
            super().do_GET()

    def _json(self, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # Silence default logging


if __name__ == '__main__':
    os.chdir(UI_DIR)
    server = HTTPServer(('0.0.0.0', PORT), KroniqoHandler)
    print(f'Kroniqo UI → http://localhost:{PORT}')
    print(f'API        → http://localhost:{PORT}/api/biography')
    print(f'Press Ctrl+C to stop\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
