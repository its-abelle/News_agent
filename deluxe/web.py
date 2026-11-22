"""Loopback-only HTTP server for News Agent; no additional web dependencies."""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .adapters import AdapterError
from .service import NewsAgent, ServiceError


class Application:
    def __init__(self, service, port=8765):
        self.service, self.port = service, port
        self.token = secrets.token_urlsafe(32)

    def handle(self, method, path, headers, body=b""):
        base_headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "no-referrer",
                        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                                   "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                                                   "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
        def result(status, value, kind="application/json; charset=utf-8", extra=None):
            data = json.dumps(value).encode() if kind.startswith("application/json") else value
            return status, dict(base_headers, **{"Content-Type": kind}, **(extra or {})), data
        try:
            hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
            if headers.get("Host") not in hosts:
                raise ServiceError("This workspace accepts local requests only.", 403)
            path = unquote(urlsplit(path).path)
            if method in {"POST", "PUT"}:
                origin = headers.get("Origin")
                if origin and origin not in {f"http://{host}" for host in hosts}:
                    raise ServiceError("Request origin not allowed.", 403)
                if headers.get("X-News-Agent-Token") != self.token:
                    raise ServiceError("Session expired. Refresh the workspace and try again.", 403)
                if len(body) > 1_100_000:
                    raise ServiceError("Request is too large.", 413)
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError) as error:
                    raise ServiceError("Request must contain valid JSON.") from error
                if not isinstance(payload, dict):
                    raise ServiceError("Request must contain a JSON object.")
            else:
                payload = {}
            if method == "GET" and path in {"/", "/app.js", "/style.css"}:
                name, kind = {"/": ("index.html", "text/html; charset=utf-8"),
                              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                              "/style.css": ("style.css", "text/css; charset=utf-8")}[path]
                content = Path(__file__).with_name("ui").joinpath(name).read_bytes()
                if path == "/":
                    content = content.replace(b"__SESSION_TOKEN__", self.token.encode())
                return result(200, content, kind)
            if method == "GET" and path == "/api/settings":
                return result(200, self.service.settings())
            if method == "GET" and path == "/api/runs":
                return result(200, {"runs": self.service.list_runs()})
            if method == "POST" and path == "/api/runs":
                return result(202, self.service.discover(payload))
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
                run_id = parts[2]
                if len(parts) == 3 and method == "GET":
                    return result(200, self.service.detail(run_id))
                if len(parts) == 4 and parts[3] == "resume" and method == "POST":
                    return result(202, self.service.resume(run_id, payload))
                if len(parts) == 5 and parts[3] == "documents" and method == "PUT":
                    return result(200, self.service.save_document(run_id, parts[4], payload.get("content")))
                if len(parts) == 5 and parts[3] == "files" and method == "GET":
                    document = next((doc for doc in self.service.documents(run_id) if doc["name"] == parts[4]), None)
                    if document is None:
                        raise ServiceError("Document not found.", 404)
                    filename = document["name"].replace(".md", "-edited.md") if document["edited"] else document["name"]
                    return result(200, document["content"].encode(), "text/markdown; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{filename}"'})
            raise ServiceError("Page not found.", 404)
        except ServiceError as error:
            return result(error.status, {"error": str(error)})
        except (AdapterError, ValueError) as error:
            return result(400, {"error": str(error)})
        except Exception:
            return result(500, {"error": "The workspace could not complete this request. Refresh and try again."})


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if size < 0 or size > 1_100_000:
                self.send_error(413)
                return
            data = self.rfile.read(size) if size else b""
            status, headers, content = app.handle(self.command, self.path, self.headers, data)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = respond
        do_POST = respond
        do_PUT = respond

        def log_message(self, format, *args):
            # Run IDs and content stay out of HTTP access logs.
            pass
    return Handler


def serve(home, port=8765):
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    service = NewsAgent(home)
    app = Application(service, port)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    except Exception:
        service.close()
        raise
    app.port = server.server_address[1]
    print(f"News Agent is running at http://127.0.0.1:{app.port}", flush=True)
    print(f"Saved runs: {home}\nKeep this terminal open. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nClosing News Agent. Any active reporting will finish its saved work.")
    finally:
        server.server_close()
        service.close()
