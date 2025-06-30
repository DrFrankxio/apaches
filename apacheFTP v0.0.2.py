import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
import os, hashlib, secrets
from http import cookies

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
            if not user:
                self.redirect("/login")
                return
            self.redirect("/editor")
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
        if parsed.path == "/editor":
            if not user:
                self.redirect("/login")
                return
            self.serve_editor(user)
            return
        file_path = self.translate_path(parsed.path)
        if os.path.isfile(file_path):
            super().do_GET()
            return
        self.send_error(404, "No encontrado")

    def do_POST(self):
        parsed = urlparse(self.path)
        user = obtener_usuario_session(self)
        if parsed.path == "/login":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            usuarios = cargar_usuarios()
            username = params.get("usuario", [""])[0].strip()
            password = params.get("password", [""])[0]
            mensaje = ""
            if not username or not password:
                mensaje = "Usuario y contraseña requeridos."
            elif username not in usuarios or usuarios[username] != hash_password(password):
                mensaje = "Usuario o contraseña incorrectos."
            else:
                sid = crear_cookie_session(username)
                self.send_response(302)
                self.send_header("Set-Cookie", f"sessionid={sid}; Path=/")
                self.send_header("Location", "/editor")
                self.end_headers()
                return
            self.serve_login(mensaje)
            return
        if parsed.path == "/nuevo_usuario":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            usuarios = cargar_usuarios()
            username = params.get("usuario", [""])[0].strip()
            password = params.get("password", [""])[0]
            mensaje = ""
            if not username or not password:
                mensaje = "Usuario y contraseña requeridos."
            elif username in usuarios:
                mensaje = "Ese usuario ya existe."
            elif ':' in username:
                mensaje = "El usuario no puede contener dos puntos."
            else:
                guardar_usuario(username, password)
                crear_carpeta_usuario(username)
                mensaje = "Usuario creado. Ahora inicia sesión."
                self.serve_login(mensaje)
                return
            self.serve_nuevo_usuario(mensaje)
            return
        if parsed.path == "/editor":
            if not user:
                self.redirect("/login")
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            action = params.get("accion", [""])[0]
            archivo = params.get("archivo", [""])[0]
            mensaje = ""
            contenido = ""
            user_dir = crear_carpeta_usuario(user)
            try:
                if action == "leer" and archivo:
                    ruta = safe_join(user_dir, archivo)
                    with open(ruta, "r", encoding="utf-8") as f:
                        contenido = f.read()
                    mensaje = f"Archivo '{archivo}' leído."
                elif action == "guardar" and archivo:
                    ruta = safe_join(user_dir, archivo)
                    contenido = params.get("contenido", [""])[0]
                    with open(ruta, "w", encoding="utf-8") as f:
                        f.write(contenido)
                    mensaje = f"Archivo '{archivo}' guardado."
                elif action == "borrar" and archivo:
                    ruta = safe_join(user_dir, archivo)
                    os.remove(ruta)
                    archivo = ""
                    mensaje = f"Archivo borrado."
            except Exception as e:
                mensaje = f"Error: {e}"
            self.serve_editor(user, archivo=archivo, contenido=contenido, mensaje=mensaje)
            return
        self.send_error(404, "No encontrado")

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

    def serve_editor(self, user, archivo="", contenido="", mensaje=""):
        user_dir = crear_carpeta_usuario(user)
        archivos = [f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f))]
        archivos_listado = "<br>".join(archivos) if archivos else "No hay archivos aún."
        html = f"""
<!DOCTYPE html>
<html><head><title>FTP Web - Editor</title><meta charset="utf-8"/></head>
<body>
<h2>FTP Web - Editor de archivos</h2>
<p>Bienvenido, <b>{user}</b> | <a href="/logout">Cerrar sesión</a></p>
{f"<p style='color:green'>{mensaje}</p>" if mensaje and not mensaje.startswith("Error") else ""}
{f"<p style='color:red'>{mensaje}</p>" if mensaje and mensaje.startswith("Error") else ""}

<form method="post" style="margin-bottom:1em;">
    <label>Archivo: 
        <input type="text" name="archivo" value="{archivo}" placeholder="ejemplo.txt" autofocus/>
    </label>
    <input type="hidden" name="accion" value="leer"/>
    <button type="submit">Leer</button>
    <button type="submit" name="accion" value="borrar" onclick="return confirm('¿Borrar archivo?')">Borrar</button>
</form>

<form method="post">
    <input type="hidden" name="archivo" value="{archivo}"/>
    <input type="hidden" name="accion" value="guardar"/>
    <textarea name="contenido" rows="20" cols="80" style="width:98%">{contenido}</textarea><br>
    <button type="submit">Guardar</button>
</form>

<p><b>Archivos en tu carpeta:</b><br>{archivos_listado}</p>
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
    PORT = 8080
    with socketserver.ThreadingTCPServer(("", PORT), FTPWebHandler) as httpd:
        print(f"Servidor FTP Web corriendo en http://localhost:{PORT}/")
        print("Cada usuario tiene su propia carpeta de archivos.")
        httpd.serve_forever()