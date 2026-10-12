# /// script
# requires-python = ">=3.13"
# ///
"""A webhook receiver for trying the engine's --webhook: prints each alert it gets.

    uv run scripts/webhook_echo.py            # listens on http://localhost:9000
    uv run engine --webhook http://localhost:9000

Use --fail N to answer the first N requests with 503, to watch the engine retry.
"""

import argparse
import contextlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--fail", type=int, default=0, metavar="N", help="503 the first N requests")
    args = parser.parse_args()
    failures_left = args.fail

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal failures_left
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            if failures_left > 0:
                failures_left -= 1
                self.send_response(503)
            else:
                alert = json.loads(body)
                print(json.dumps(alert, indent=2), flush=True)
                self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} {format % args}", flush=True)

    server = ThreadingHTTPServer(("localhost", args.port), Handler)
    print(f"listening on http://localhost:{args.port}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
