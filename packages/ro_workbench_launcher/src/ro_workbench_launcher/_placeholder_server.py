"""Phase 3 Spike C 占位 server：后端未实现时用 http.server 返回简单页面。"""
import http.server
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h1>RO Workbench</h1><p>Starting...</p>")

    def log_message(self, *args: object) -> None:
        pass  # 抑制访问日志


httpd = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
httpd.serve_forever()
