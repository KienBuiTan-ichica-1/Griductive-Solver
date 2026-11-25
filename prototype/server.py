"""Serve the UI prototype.

    python server.py                         page on 8001, API expected on 8000
    python server.py 9001                    page on port 9001
    python server.py 9001 --api 9000         page on 9001, API on port 9000
    python server.py --api http://host:8000  API on another host

The API itself is started separately:  python main.py 9000
"""
import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 8001
DEFAULT_API = "8000"


class Handler(SimpleHTTPRequestHandler):
    api_base = f"http://127.0.0.1:{DEFAULT_API}"

    def do_GET(self):
        if self.path.split("?")[0] == "/config.js":      # tells the page where the API is
            body = f"window.GRIDUCTIVE_CONFIG = {json.dumps({'apiBase': self.api_base})};\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")     # always show the latest edit
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description="Serve the Griductive UI prototype.")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT, help=f"port for this page (default {DEFAULT_PORT})")
    parser.add_argument("--api", default=DEFAULT_API, help=f"API port or full URL (default {DEFAULT_API})")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    args = parser.parse_args()

    Handler.api_base = args.api.rstrip("/") if args.api.startswith("http") else f"http://127.0.0.1:{args.api}"
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(ROOT)))
    print(f"UI  : http://{args.host}:{args.port}")
    print(f"API : {Handler.api_base}  (start it with: python main.py)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()