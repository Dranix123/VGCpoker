import http.cookies
import ipaddress
import json
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / 'admin'


def start_admin(snapshot, token_path, port=4143):
    token_path = Path(token_path)
    if not token_path.exists():
        with os.fdopen(os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file: file.write(secrets.token_urlsafe(32))
    token_path.chmod(0o600)
    token = token_path.read_text().strip()
    if len(token) < 32: raise ValueError('管理口令文件至少需要 32 个字符。')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def local(self):
            return (ipaddress.ip_address(self.client_address[0]).is_loopback and
                    self.headers.get('Host') in ('localhost:%d' % self.server.server_port, '127.0.0.1:%d' % self.server.server_port) and
                    not any(self.headers.get(k) for k in ('Forwarded','X-Forwarded-For','X-Forwarded-Host','CF-Connecting-IP')))

        def authorized(self):
            cookie = http.cookies.SimpleCookie()
            try: cookie.load(self.headers.get('Cookie',''))
            except http.cookies.CookieError: return False
            supplied = cookie.get('vgc_admin')
            bearer = self.headers.get('Authorization','').removeprefix('Bearer ')
            return secrets.compare_digest((supplied.value if supplied else bearer).encode(), token.encode())

        def send(self, content, status=200, mime='application/json; charset=utf-8', cookie=None, location=None):
            data = json.dumps(content).encode() if isinstance(content,dict) else content.encode() if isinstance(content,str) else content
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','same-origin')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
            if cookie: self.send_header('Set-Cookie',cookie)
            if location: self.send_header('Location',location)
            self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if not self.local(): return self.send({'error':'Not found'},404)
            path = urllib.parse.urlsplit(self.path).path
            if not self.authorized():
                if path == '/': return self.send((ASSETS/'login.html').read_bytes(),mime='text/html; charset=utf-8')
                return self.send({'error':'请先输入管理口令。'},401)
            if path == '/api/stats': return self.send(snapshot())
            assets = {'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
            if path not in assets: return self.send({'error':'Not found'},404)
            name, mime = assets[path]
            return self.send((ASSETS/name).read_bytes(),mime=mime+'; charset=utf-8')

        def do_POST(self):
            if not self.local(): return self.send({'error':'Not found'},404)
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+self.headers.get('Host',''): return self.send({'error':'跨站请求被拒绝。'},403)
            path = urllib.parse.urlsplit(self.path).path
            if path == '/logout': return self.send('',303,cookie='vgc_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',location='/')
            if path != '/login': return self.send({'error':'Not found'},404)
            try: size = int(self.headers.get('Content-Length','0'))
            except ValueError: return self.send({'error':'请求无效。'},400)
            if not 0 < size <= 1024: return self.send({'error':'请求无效。'},400)
            supplied = urllib.parse.parse_qs(self.rfile.read(size).decode(errors='replace')).get('token',[''])[0]
            if not secrets.compare_digest(supplied.encode(),token.encode()): return self.send('管理口令不正确，请返回重试。',401,'text/plain; charset=utf-8')
            return self.send('',303,cookie='vgc_admin='+token+'; HttpOnly; SameSite=Strict; Path=/',location='/')

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
