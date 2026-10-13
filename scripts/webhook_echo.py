# /// script
# requires-python = ">=3.13"
# ///
"""A webhook receiver for trying alerts out: prints each alert it gets.

    uv run scripts/webhook_echo.py            # listens on http://localhost:9000
    uv run engine --webhook http://localhost:9000

In Docker Compose it is the `webhook` service the notifier delivers to.
GET /alerts returns every alert received so far, in order, as a JSON array
(the smoke test uses it to check the notifier delivered each alert once).

Use --fail N to answer the first N requests with 503, to watch the sender retry.
"""

import argparse
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="localhost", help="address to listen on")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--fail", type=int, default=0, metavar="N", help="503 the first N requests")
    args = parser.parse_args()
    failures_left = args.fail
    received: list[Any] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal failures_left
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            with lock:
                fail = failures_left > 0
                failures_left -= fail
            if fail:
                self.send_response(503)
            else:
                alert = json.loads(body)
                with lock:
                    received.append(alert)
                print(json.dumps(alert, indent=2), flush=True)
                self.send_response(204)
            self.end_headers()

        def do_GET(self) -> None:
            if self.path != "/alerts":
                self.send_error(404)
                return
            with lock:
                body = json.dumps(received).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            if self.command != "GET":
                print(f"{self.address_string()} {format % args}", flush=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
