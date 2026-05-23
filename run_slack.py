"""Slack bot runner."""

import os
from pathlib import Path
from dotenv import load_dotenv
from threading import Thread
from http.server import HTTPServer, SimpleHTTPRequestHandler


def start_health_server():
    """Simple HTTP health check server for Cloud Run."""
    class HealthHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            pass  # suppress logs

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# Load slack credentials
env_path = Path(__file__).parent / ".env.slack"
if env_path.exists():
    load_dotenv(env_path)

from slack_bot import run_slack_bot

if __name__ == "__main__":
    # Start health check server in background thread for Cloud Run
    Thread(target=start_health_server, daemon=True, name="health-server").start()
    run_slack_bot()
