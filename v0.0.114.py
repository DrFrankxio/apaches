import http.server
import socketserver
from mako.template import Template
from urllib.parse import urlparse, parse_qs
import os
import mimetypes

def pedir_directorio(mensaje, defecto):
    ruta = input(mensaje).strip()
    if not ruta:
        ruta = defecto
    return os.path.abspath(ruta)

WEB_ROOT = pedir_directorio("Carpeta base para servir archivos web (.mako, .html): ", os.getcwd())
BASE_DIR_1 = pedir_directorio("Introduce la PRIMERA carpeta de archivos para leer/escribir: ", os.getcwd())
BASE_DIR_2 = pedir_directorio("Introduce la SEGUNDA carpeta de archivos (opcional): ", os.getcwd() + "_alt")

BASE_DIRS = {
    "principal": BASE_DIR_1,
    "alternativo": BASE_DIR_2
}

def safe_join(base, *paths):
    final_path = os.path.abspath(os.path.join(base, *paths))
    if not final_path.startswith(base):
        raise ValueError("Intento de acceso fuera del directorio permitido.")
    return final_path

class MakoReadWriteHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = os.path.normpath(os.path.join(WEB_ROOT, *path.strip('/').split('/')))
        return path

    def do_GET(self):
        parsed = urlparse(self.path)
        file_path = self.translate_path(parsed.path)
        if file_path.endswith('.mako') and os.path.isfile(file_path):
            params = parse_qs(parsed.query)
            self.serve_mako(file_path, params, {})
            return
        elif os.path.isfile(file_path):
            self.serve_static(file_path)
            return
        super().do_GET()

    def serve_static(self, file_path):
        try:
            mime_type, _ = mimetypes.guess_type(file_path)
            # Forzar el MIME correcto para .mp4
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.mp4':
                mime_type = "video/mp4"
            self.send_response(200)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        except Exception as e:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"<pre>No se pudo servir el archivo: {e}</pre>".encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        file_path = self.translate_path(parsed.path)
        if file_path.endswith('.mako') and os.path.isfile(file_path):
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            result = {}

            ubicacion = params.get("ubicacion", ["principal"])[0]
            base_dir = BASE_DIRS.get(ubicacion, BASE_DIR_1)

            # Lectura de archivo
            if params.get("accion", [""])[0] == "leer":
                archivo = params.get("archivo_leer", [""])[0]
                if archivo:
                    try:
                        ruta = safe_join(base_dir, archivo)
                        with open(ruta, "r", encoding="utf-8") as f:
                            contenido = f.read()
                        result["leer_ok"] = True
                        result["archivo_leer"] = archivo
                        result["contenido_leido"] = contenido
                        result["ubicacion"] = ubicacion
                    except Exception as e:
                        result["leer_ok"] = False
                        result["error_leer"] = str(e)
                        result["ubicacion"] = ubicacion
            # Escritura de archivo
            elif params.get("accion", [""])[0] == "escribir":
                archivo = params.get("archivo_escribir", [""])[0]
                contenido = params.get("contenido_escribir", [""])[0]
                if archivo:
                    try:
                        ruta = safe_join(base_dir, archivo)
                        with open(ruta, "w", encoding="utf-8") as f:
                            f.write(contenido)
                        result["escribir_ok"] = True
                        result["archivo_escribir"] = archivo
                        result["ubicacion"] = ubicacion
                    except Exception as e:
                        result["escribir_ok"] = False
                        result["error_escribir"] = str(e)
                        result["ubicacion"] = ubicacion
            self.serve_mako(file_path, {}, result)
            return
        super().do_POST()

    def serve_mako(self, file_path, params, result):
        try:
            template = Template(filename=file_path)
            html = template.render(params=params, result=result, ubicaciones=BASE_DIRS.keys(), cssfile="estilos.css")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"<pre>Error ejecutando Mako: {e}</pre>".encode("utf-8"))

try:
    PORT = int(input("Elige tu puerto: ") or "8000")
except ValueError:
    PORT = 8000

with socketserver.TCPServer(("", PORT), MakoReadWriteHandler) as httpd:
    print(f"Servidor corriendo en el puerto {PORT}")
    print(f"Web root: {WEB_ROOT}")
    print(f"Ubicaciones de archivos:")
    for nombre, ruta in BASE_DIRS.items():
        print(f"  {nombre}: {ruta}")
    httpd.serve_forever()