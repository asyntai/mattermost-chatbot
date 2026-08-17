"""A stand-in for the Asyntai chat API, used to test the Mattermost plugin.

It copies the real contract: Bearer auth, POST /api/v1/chat/, and the same
JSON shape for both success and failure. Special questions trigger the error
paths, so the plugin can be tested without a real account.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

VALID_KEY = "test-key-12345"
CALLS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/_calls":
            self._send(200, CALLS)
            return
        self._send(404, {"success": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/api/v1/chat/":
            self._send(404, {"success": False, "error": "not found"})
            return

        auth = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")

        try:
            data = json.loads(raw)
        except ValueError:
            self._send(400, {"success": False, "error": "Invalid JSON body"})
            return

        CALLS.append({
            "auth": auth,
            "agent": self.headers.get("User-Agent", ""),
            "body": data,
        })

        if auth != "Bearer " + VALID_KEY:
            self._send(401, {"success": False, "error": "Invalid API key"})
            return

        message = (data.get("message") or "").strip()

        if message == "make it fail":
            self._send(403, {"success": False,
                             "error": "Message limit reached. Please upgrade your plan."})
            return

        self._send(200, {
            "success": True,
            "response": "You asked: %s. Our refund window is 30 days from delivery." % message,
            "session_id": data.get("session_id", ""),
        })


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
