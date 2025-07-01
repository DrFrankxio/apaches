import http.server
import socketserver
from urllib.parse import urlparse, parse_qs, unquote
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

def parent_folder(ruta_relativa):
    if not ruta_relativa:
        return ""
    partes = ruta_relativa.replace("\\","/").strip("/").split("/")
    return "/".join(partes[:-1])

def es_html(nombre):
    return nombre.lower().endswith(".html")

def listar_htdocs():
    """Devuelve un dict de usuario -> lista de archivos .html en su carpeta."""
    resultado = {}
    if not os.path.exists(USERS_BASE):
        return resultado
    for usuario in os.listdir(USERS_BASE):
        user_dir = os.path.join(USERS_BASE, usuario)
        if not os.path.isdir(user_dir):
            continue
        archivos = []
        for root, dirs, files in os.walk(user_dir):
            for f in files:
                if es_html(f):
                    ruta_rel = os.path.relpath(os.path.join(root, f), user_dir)
                    archivos.append(ruta_rel.replace("\\", "/"))
        if archivos:
            resultado[usuario] = archivos
    return resultado

class FTPWebHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = os.path.normpath(os.path.join(WEB_ROOT, *path.strip('/').split('/')))
        return path

    def do_GET(self):
        parsed = urlparse(self.path)
        user = obtener_usuario_session(self)
        file_path = self.translate_path(parsed.path)
        # Bloquear acceso a usuarios.txt y otros archivos de control
        if os.path.abspath(file_path) == os.path.abspath(USERS_FILE):
            self.send_error(403, "Acceso prohibido")
            return

        if parsed.path == "/":
            self.redirect("/servidores")
            return
        if parsed.path == "/servidores":
            self.serve_servidores()
            return
        if parsed.path.startswith("/servidores/"):
            partes = parsed.path.strip("/").split("/", 2)
            if len(partes) == 3:
                usuario = partes[1]
                archivo = partes[2]
                user_dir = os.path.join(USERS_BASE, usuario)
                try:
                    ruta = safe_join(user_dir, archivo)
                except Exception:
                    self.send_error(403, "Acceso denegado")
                    return
                if os.path.isfile(ruta) and es_html(ruta):
                    with open(ruta, "r", encoding="utf-8") as f:
                        contenido = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(contenido.encode("utf-8"))
                    return
                else:
                    self.send_error(404, "Archivo no encontrado o no es HTML")
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
            params = parse_qs(parsed.query)
            carpeta = params.get("carpeta", [""])[0]
            archivo = params.get("archivo", [""])[0] if "archivo" in params else ""
            self.serve_editor(user, carpeta_rel=carpeta, archivo=archivo)
            return
        # Bloqueo de otros archivos de control aquí si quieres
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
            carpeta_rel = params.get("carpeta_rel", [""])[0]
            mensaje = ""
            contenido = ""
            user_dir = crear_carpeta_usuario(user)
            ruta_base = safe_join(user_dir, carpeta_rel)
            try:
                if action == "leer" and archivo:
                    ruta = safe_join(ruta_base, archivo)
                    with open(ruta, "r", encoding="utf-8") as f:
                        contenido = f.read()
                    mensaje = f"Archivo '{archivo}' leído."
                elif action == "guardar" and archivo:
                    ruta = safe_join(ruta_base, archivo)
                    contenido = params.get("contenido", [""])[0]
                    with open(ruta, "w", encoding="utf-8") as f:
                        f.write(contenido)
                    mensaje = f"Archivo '{archivo}' guardado."
                elif action == "borrar" and archivo:
                    ruta = safe_join(ruta_base, archivo)
                    os.remove(ruta)
                    archivo = ""
                    mensaje = f"Archivo borrado."
                elif action == "crear_carpeta":
                    carpeta = params.get("carpeta", [""])[0]
                    if carpeta:
                        ruta_carpeta = safe_join(ruta_base, carpeta)
                        os.makedirs(ruta_carpeta, exist_ok=True)
                        mensaje = f"Carpeta '{carpeta}' creada."
                    else:
                        mensaje = "Debes indicar el nombre de la carpeta a crear."
                elif action == "entrar_carpeta":
                    carpeta_click = params.get("carpeta_click", [""])[0]
                    if carpeta_click:
                        carpeta_rel = os.path.normpath(os.path.join(carpeta_rel, carpeta_click))
                elif action == "subir_carpeta":
                    carpeta_rel = parent_folder(carpeta_rel)
            except Exception as e:
                mensaje = f"Error: {e}"
            self.serve_editor(user, carpeta_rel=carpeta_rel, archivo=archivo, contenido=contenido, mensaje=mensaje)
            return
        self.send_error(404, "No encontrado")

    def serve_servidores(self):
        """Página pública con enlaces a todos los .html de todos los usuarios."""
        htdocs = listar_htdocs()
        filas = []
        for user, archivos in sorted(htdocs.items()):
            filas.append(f"<h3>{user}</h3><ul>")
            for f in sorted(archivos):
                url = f"/servidores/{user}/{f}"
                filas.append(f'<li><a href="{url}">{f}</a></li>')
            filas.append("</ul>")
        if not filas:
            filas.append("<p>No hay archivos .html de usuarios aún.</p>")
        html = f"""
<!DOCTYPE html>
<html><head><title>Servidores web de usuarios</title><meta charset="utf-8"/></head>
<body>
<h2>Servidores web de usuarios</h2>
<p>Aquí aparecen todos los archivos .html de cada usuario.<br/>
Puedes enlazar directamente a <code>/servidores/usuario/archivo.html</code></p>
{''.join(filas)}
</body></html>
"""
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

    def serve_editor(self, user, carpeta_rel="", archivo="", contenido="", mensaje=""):
        user_dir = crear_carpeta_usuario(user)
        ruta_base = safe_join(user_dir, carpeta_rel)
        entradas = os.listdir(ruta_base) if os.path.exists(ruta_base) else []
        archivos = [f for f in entradas if os.path.isfile(os.path.join(ruta_base, f))]
        carpetas = [d for d in entradas if os.path.isdir(os.path.join(ruta_base, d))]
        archivos_listado = "<br>".join(archivos) if archivos else "No hay archivos aún."
        carpetas_listado = ""
        for carpeta in carpetas:
            carpetas_listado += f"""<form method="post" style="display:inline;margin:0;padding:0">
    <input type="hidden" name="carpeta_rel" value="{carpeta_rel}"/>
    <input type="hidden" name="carpeta_click" value="{carpeta}"/>
    <input type="hidden" name="accion" value="entrar_carpeta"/>
    <button type="submit" style="background:none;border:none;color:blue;text-decoration:underline;cursor:pointer">{carpeta}/</button>
    </form> """
        if not carpetas_listado:
            carpetas_listado = "No hay carpetas aún."
        html = f"""
<!DOCTYPE html>
<html><head><title>FTP Web - Editor</title><meta charset="utf-8"/></head>
<body>
<h2>FTP Web - Editor de archivos y carpetas</h2>
<p>Bienvenido, <b>{user}</b> | <a href="/logout">Cerrar sesión</a></p>
{f"<p style='color:green'>{mensaje}</p>" if mensaje and not mensaje.startswith("Error") else ""}
{f"<p style='color:red'>{mensaje}</p>" if mensaje and mensaje.startswith("Error") else ""}

<p>
Ruta actual: /{carpeta_rel}
{"<form method='post' style='display:inline'><input type='hidden' name='carpeta_rel' value='" + carpeta_rel + "'/><input type='hidden' name='accion' value='subir_carpeta'/><button type='submit'>⬆️ Subir carpeta</button></form>" if carpeta_rel else ""}
</p>

<!-- Crear carpeta -->
<form method="post" style="margin-bottom:1em;">
    <input type="hidden" name="carpeta_rel" value="{carpeta_rel}"/>
    <label>Crear carpeta: 
        <input type="text" name="carpeta" placeholder="nombre_carpeta"/>
    </label>
    <input type="hidden" name="accion" value="crear_carpeta"/>
    <button type="submit">Crear carpeta</button>
</form>

<!-- Leer, borrar archivo -->
<form method="post" style="margin-bottom:1em;">
    <input type="hidden" name="carpeta_rel" value="{carpeta_rel}"/>
    <label>Archivo: 
        <input type="text" name="archivo" value="{archivo}" placeholder="ejemplo.html" autofocus/>
    </label>
    <input type="hidden" name="accion" value="leer"/>
    <button type="submit">Leer</button>
    <button type="submit" name="accion" value="borrar" onclick="return confirm('¿Borrar archivo?')">Borrar</button>
</form>

<!-- Guardar archivo -->
<form method="post">
    <input type="hidden" name="carpeta_rel" value="{carpeta_rel}"/>
    <input type="hidden" name="archivo" value="{archivo}"/>
    <input type="hidden" name="accion" value="guardar"/>
    <textarea name="contenido" rows="20" cols="80" style="width:98%">{contenido}</textarea><br>
    <button type="submit">Guardar</button>
</form>

<p><b>Carpetas en esta carpeta:</b><br>{carpetas_listado}</p>
<p><b>Archivos en esta carpeta:</b><br>{archivos_listado}</p>
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
    print(f"Servidor FTP Web SOLO HTML corriendo en http://localhost:{PORT}/")
    print("Cada usuario SOLO puede crear, leer y borrar archivos.")
    print("Todos los archivos .html públicos en /servidores")
    with socketserver.ThreadingTCPServer(("", PORT), FTPWebHandler) as httpd:
        httpd.serve_forever()