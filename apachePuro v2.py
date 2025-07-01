import http.server
import socketserver
from urllib.parse import urlparse, parse_qs, unquote
import os, hashlib, secrets
from http import cookies

try:
    from mako.template import Template
except ImportError:
    Template = None

WEB_ROOT = os.path.abspath(os.path.dirname(__file__))
USERS_FILE = os.path.join(WEB_ROOT, "usuarios.txt")
USERS_BASE = os.path.join(WEB_ROOT, "usuarios")
os.makedirs(USERS_BASE, exist_ok=True)
SESSIONS = {}

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def cargar_usuarios():
    usuarios = {}
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if ":" not in line: continue
                user, pwdhash = line.split(":", 1)
                usuarios[user] = pwdhash
    return usuarios

def guardar_usuario(user, pwd):
    with open(USERS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{user}:{hash_password(pwd)}\n")

def crear_carpeta_usuario(username):
    user_dir = os.path.join(USERS_BASE, username)
    os.makedirs(user_dir, exist_ok=True)
    htdocs_dir = os.path.join(user_dir, "htdocs")
    os.makedirs(htdocs_dir, exist_ok=True)
    return user_dir

def crear_cookie_session(user):
    sid = secrets.token_hex(16)
    SESSIONS[sid] = user
    return sid

def obtener_usuario_session(handler):
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header: return None
    c = cookies.SimpleCookie()
    c.load(cookie_header)
    sid = c.get("sessionid")
    if sid and sid.value in SESSIONS:
        return SESSIONS[sid.value]
    return None

def cerrar_session(handler):
    cookie_header = handler.headers.get("Cookie", "")
    c = cookies.SimpleCookie()
    c.load(cookie_header)
    sid = c.get("sessionid")
    if sid and sid.value in SESSIONS:
        del SESSIONS[sid.value]

def safe_join(base, *paths):
    final_path = os.path.abspath(os.path.join(base, *paths))
    if not final_path.startswith(base):
        raise ValueError("Intento de acceso fuera del directorio permitido.")
    return final_path

def es_htmlo_mako(fname):
    return fname.endswith(".html") or fname.endswith(".mako")

def listar_htdocs():
    """Devuelve un dict de usuario -> lista de archivos en htdocs."""
    resultado = {}
    if not os.path.exists(USERS_BASE):
        return resultado
    for usuario in os.listdir(USERS_BASE):
        htdocs = os.path.join(USERS_BASE, usuario, "htdocs")
        if os.path.exists(htdocs) and os.path.isdir(htdocs):
            archivos = []
            for root, dirs, files in os.walk(htdocs):
                for f in files:
                    if f.endswith(".html") or f.endswith(".mako"):
                        ruta_rel = os.path.relpath(os.path.join(root, f), htdocs)
                        archivos.append(ruta_rel.replace("\\", "/"))
            if archivos:
                resultado[usuario] = archivos
    return resultado

def encontrar_index(usuario, subruta=""):
    """Busca index.html o index.mako en la subruta de htdocs del usuario."""
    htdocs = os.path.join(USERS_BASE, usuario, "htdocs")
    destino = safe_join(htdocs, subruta)
    for nombre in ("index.html", "index.mako"):
        idxfile = os.path.join(destino, nombre)
        if os.path.isfile(idxfile):
            return nombre
    return None

class FTPWebHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = os.path.normpath(os.path.join(WEB_ROOT, *path.strip('/').split('/')))
        return path

    def do_GET(self):
        parsed = urlparse(self.path)
        user = obtener_usuario_session(self)
        if parsed.path == "/":
            self.redirect("/servidores")
            return
        if parsed.path == "/servidores":
            self.serve_servidores()
            return
        if parsed.path.startswith("/web/"):
            # /web/usuario/ -> index.html/mako
            # /web/usuario/archivo
            partes = parsed.path.strip("/").split("/", 2)
            if len(partes) >= 2:
                usuario = partes[1]
                subruta = ""
                if len(partes) == 3:
                    subruta = unquote(partes[2])
                self.serve_web_file(usuario, subruta)
                return
        if parsed.path == "/login":
            self.serve_login()
            return
        if parsed.path == "/logout":
            cerrar_session(self)
            self.send_response(302)
            self.send_header("Set-Cookie", "sessionid=; Path=/; Max-Age=0")
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if parsed.path == "/nuevo_usuario":
            self.serve_nuevo_usuario()
            return
        # Aquí iría la lógica de editor/FTP, omítela si solo quieres la parte web.
        self.send_error(404, "No encontrado")

    def serve_servidores(self):
        """Muestra todos los htdocs de todos los usuarios como enlaces web."""
        htdocs = listar_htdocs()
        filas = []
        for user, archivos in sorted(htdocs.items()):
            filas.append(f"<h3>{user}</h3><ul>")
            idx = encontrar_index(user)
            if idx:
                filas.append(f'<li><a href="/web/{user}/">{user}/htdocs/ (index)</a></li>')
            for f in sorted(archivos):
                if f == idx:
                    continue
                filas.append(f'<li><a href="/web/{user}/{f}">{f}</a></li>')
            filas.append("</ul>")
        if not filas:
            filas.append("<p>No hay webs de usuarios aún.</p>")
        html = f"""
<!DOCTYPE html>
<html><head><title>Servidores web de usuarios</title><meta charset="utf-8"/></head>
<body>
<h2>Servidores web de usuarios</h2>
<p>Aquí aparecen todos los archivos .html y .mako en htdocs de cada usuario.<br/>
Puedes enlazar directamente a <code>/web/usuario/archivo</code> o a <code>/web/usuario/</code> para el index.</p>
{''.join(filas)}
</body></html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def serve_web_file(self, usuario, subruta):
        """Sirve archivos .html o .mako como web, o index si subruta es carpeta."""
        htdocs = os.path.join(USERS_BASE, usuario, "htdocs")
        if not os.path.exists(htdocs):
            self.send_error(404, "Usuario o htdocs no existen")
            return
        fs_path = safe_join(htdocs, subruta)
        if os.path.isdir(fs_path):
            idx = encontrar_index(usuario, subruta)
            if idx:
                fs_path = os.path.join(fs_path, idx)
                subruta = os.path.join(subruta, idx) if subruta else idx
            else:
                self.listar_dir_web(usuario, subruta)
                return
        if not os.path.isfile(fs_path):
            self.send_error(404, "Archivo no encontrado")
            return
        if fs_path.endswith(".html"):
            with open(fs_path, "r", encoding="utf-8") as f:
                contenido = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(contenido.encode("utf-8"))
        elif fs_path.endswith(".mako"):
            if Template is None:
                self.send_error(500, "Mako no instalado")
                return
            with open(fs_path, "r", encoding="utf-8") as f:
                plantilla = f.read()
            try:
                html = Template(plantilla).render()
            except Exception as e:
                html = f"<pre>Error de Mako: {e}</pre>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(html).encode("utf-8"))
        else:
            self.send_error(403, "Solo se sirven archivos .html o .mako")

    def listar_dir_web(self, usuario, subruta):
        """Lista los archivos y subcarpetas en htdocs de usuario/subruta."""
        htdocs = os.path.join(USERS_BASE, usuario, "htdocs")
        fs_path = safe_join(htdocs, subruta)
        if not os.path.isdir(fs_path):
            self.send_error(404, "No es carpeta")
            return
        items = os.listdir(fs_path)
        files = []
        dirs = []
        for name in items:
            full = os.path.join(fs_path, name)
            if os.path.isdir(full):
                dirs.append(name)
            elif name.endswith(".html") or name.endswith(".mako"):
                files.append(name)
        rel = subruta.rstrip("/")
        if rel:
            arriba = f'<a href="/web/{usuario}/{os.path.dirname(rel)}">⬆️ Subir</a>'
        else:
            arriba = ""
        html = f"""
<!DOCTYPE html>
<html><head><title>{usuario}/htdocs/{rel}</title><meta charset="utf-8"/></head>
<body>
<h3>{usuario}/htdocs/{rel}</h3>
{arriba}
<ul>
"""
        for d in sorted(dirs):
            url = f"/web/{usuario}/{(rel + '/' if rel else '') + d}"
            html += f'<li><b><a href="{url}">{d}/</a></b></li>'
        for f in sorted(files):
            url = f"/web/{usuario}/{(rel + '/' if rel else '') + f}"
            html += f'<li><a href="{url}">{f}</a></li>'
        html += "</ul></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def serve_login(self, mensaje=""):
        html = f"""
<!DOCTYPE html>
<html><head><title>FTP Web - Login</title><meta charset="utf-8"/></head>
<body>
<h2>FTP Web - Iniciar sesión</h2>
{f"<p style='color:red'>{mensaje}</p>" if mensaje else ""}
<form method="post">
    Usuario: <input name="usuario" autofocus/><br/>
    Contraseña: <input name="password" type="password"/><br/>
    <button type="submit">Entrar</button>
</form>
<p>¿No tienes cuenta? <a href="/nuevo_usuario">Regístrate</a></p>
</body></html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def serve_nuevo_usuario(self, mensaje=""):
        html = f"""
<!DOCTYPE html>
<html><head><title>FTP Web - Nuevo usuario</title><meta charset="utf-8"/></head>
<body>
<h2>Crear nuevo usuario</h2>
{f"<p style='color:red'>{mensaje}</p>" if mensaje else ""}
<form method="post">
    Usuario: <input name="usuario" autofocus/><br/>
    Contraseña: <input name="password" type="password"/><br/>
    <button type="submit">Crear usuario</button>
</form>
<p><a href="/login">Volver a login</a></p>
</body></html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def redirect(self, path):
        self.send_response(302)
        self.send_header("Location", path)
        self.end_headers()

if __name__ == "__main__":
    PORT = 8000
    with socketserver.ThreadingTCPServer(("", PORT), FTPWebHandler) as httpd:
        print(f"Servidor FTP Web corriendo en http://localhost:{PORT}/")
        print("Cada usuario tiene su propia carpeta htdocs para webs.")
        httpd.serve_forever()