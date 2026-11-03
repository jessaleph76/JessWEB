import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import shutil
import hashlib
import csv
import threading
import urllib.request
import json
import tempfile
import subprocess
import sys
from datetime import datetime
import tkcalendar

# ============================================================
# ⚙️ CONFIGURACIÓN DEL AUTO-ACTUALIZADOR
# REEMPLAZA estos valores con los tuyos:
# ============================================================
VERSION_ACTUAL = "1.0.0"                    # ← cámbialo al publicar nueva versión
GITHUB_REPO = "jessaleph76/JessWEB"          # ← ej: "juanperez/expedientes-medicos"
# ============================================================

# ==================== PALETA Y CONFIG ====================
PALETA = {
    "fondo":        "#F4F6F9",
    "tarjeta":      "#FFFFFF",
    "primario":     "#2563EB",
    "primario_hov": "#1D4ED8",
    "exito":        "#10B981",
    "exito_hov":    "#059669",
    "peligro":      "#EF4444",
    "peligro_hov":  "#DC2626",
    "advertencia":  "#F59E0B",
    "texto":        "#1F2937",
    "texto_suave":  "#6B7280",
    "borde":        "#E5E7EB",
    "seleccion":    "#DBEAFE",
    "header":       "#1E3A8A",
}

FUENTE = "Segoe UI"
F_TITULO   = (FUENTE, 18, "bold")
F_SUBTIT   = (FUENTE, 11)
F_LABEL    = (FUENTE, 10, "bold")
F_NORMAL   = (FUENTE, 10)
F_BOTON    = (FUENTE, 10, "bold")
F_PEQUENA  = (FUENTE, 9)

APP_DIR = os.path.join(os.path.expanduser("~"), "Documents", "ExpedientesMedicos")
ADJUNTOS_DIR = os.path.join(APP_DIR, "adjuntos")
RECURSOS_DIR = os.path.join(APP_DIR, "recursos")
DB_PATH = os.path.join(APP_DIR, "expedientes.db")
CONFIG_UPDATE_JSON = os.path.join(APP_DIR, "update_state.json")
os.makedirs(APP_DIR, exist_ok=True)
os.makedirs(ADJUNTOS_DIR, exist_ok=True)
os.makedirs(RECURSOS_DIR, exist_ok=True)


# ==================== CONEXIÓN SQLITE ====================
def conectar_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ==================== AUTO-ACTUALIZADOR ====================
def _leer_estado_update():
    try:
        with open(CONFIG_UPDATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_estado_update(estado):
    try:
        with open(CONFIG_UPDATE_JSON, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2)
    except Exception:
        pass


def _version_mayor(v_remota, v_local):
    try:
        return tuple(map(int, v_remota.split("."))) > tuple(map(int, v_local.split(".")))
    except ValueError:
        return False


def _postergado_recientemente():
    estado = _leer_estado_update()
    ts = estado.get("postergado_hasta", 0)
    return datetime.now().timestamp() < ts


def _descargar_con_progreso(url, ruta_destino, ventana_progreso):
    sha_esperado = None
    req = urllib.request.Request(url, headers={"User-Agent": "ExpedientesMedicos-Updater"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        sha_esperado = resp.headers.get("X-Checksum-Sha256")
        descargado = 0
        with open(ruta_destino, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                descargado += len(chunk)
                if total > 0:
                    pct = int(descargado * 100 / total)
                    mb = descargado / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    ventana_progreso.actualizar(pct, f"{mb:.1f} / {total_mb:.1f} MB")
                else:
                    mb = descargado / (1024 * 1024)
                    ventana_progreso.actualizar(-1, f"{mb:.1f} MB")

    if sha_esperado:
        h = hashlib.sha256()
        with open(ruta_destino, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        if h.hexdigest().lower() != sha_esperado.lower():
            try:
                os.remove(ruta_destino)
            except Exception:
                pass
            raise Exception("Checksum no coincide: el archivo está corrupto.")
    return sha_esperado


class VentanaProgresoDescarga(tk.Toplevel):
    def __init__(self, master, titulo="Descargando actualización"):
        super().__init__(master)
        self.title(titulo)
        self.geometry("500x180")
        self.configure(bg=PALETA["fondo"])
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        header = tk.Frame(self, bg=PALETA["header"], height=50)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="⬇️  " + titulo, bg=PALETA["header"], fg="white",
                 font=(FUENTE, 13, "bold")).pack(side="left", padx=20, pady=10)

        body = tk.Frame(self, bg=PALETA["fondo"], padx=25, pady=20)
        body.pack(fill="both", expand=True)

        self.lbl_estado = tk.Label(body, text="Iniciando descarga...",
                                     bg=PALETA["fondo"], fg=PALETA["texto"],
                                     font=F_NORMAL)
        self.lbl_estado.pack(anchor="w", pady=(0, 8))

        self.barra = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.barra.pack(fill="x", pady=(0, 10))

        self.lbl_detalle = tk.Label(body, text="0.0 MB",
                                      bg=PALETA["fondo"], fg=PALETA["texto_suave"],
                                      font=F_PEQUENA)
        self.lbl_detalle.pack(anchor="w")

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-500)//2}+{(sh-180)//2}")

    def actualizar(self, pct, detalle):
        if pct < 0:
            self.barra.configure(mode="indeterminate")
            self.barra.start(15)
        else:
            self.barra.configure(mode="determinate", value=pct)
        self.lbl_detalle.config(text=detalle)
        self.update_idletasks()


def _aplicar_actualizacion(nuevo_exe):
    try:
        exe_actual = sys.executable
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                "Modo desarrollo",
                "Estás ejecutando el script directamente (no empaquetado).\n"
                "La actualización se aplicaría solo en el .exe instalado.")
            return
        tmp_dir = tempfile.gettempdir()
        bat = os.path.join(tmp_dir, "actualizar_expedientes.bat")
        with open(bat, "w", encoding="utf-8") as f:
            f.write(f'''@echo off
timeout /t 2 /nobreak >nul
move /y "{nuevo_exe}" "{exe_actual}"
start "" "{exe_actual}"
del "%~f0"
''')
        subprocess.Popen(["cmd", "/c", bat], shell=True)
        tk._default_root.destroy()
        sys.exit(0)
    except Exception as e:
        messagebox.showerror("Error al actualizar", str(e))


def verificar_actualizacion(root, manual=False):
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "ExpedientesMedicos-Updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        if manual:
            messagebox.showerror("Error", f"No se pudo consultar actualizaciones:\n{e}")
        return

    tag = data.get("tag_name", "").lstrip("v")
    if not tag or not _version_mayor(tag, VERSION_ACTUAL):
        if manual:
            messagebox.showinfo("Actualizaciones",
                                f"Ya tienes la última versión ({VERSION_ACTUAL}).")
        return

    assets = data.get("assets", [])
    exe_asset = next((a for a in assets if a["name"].endswith(".exe")), None)
    if not exe_asset:
        if manual:
            messagebox.showwarning("Aviso", "La nueva versión no tiene .exe adjunto.")
        return

    if not manual and _postergado_recientemente():
        return

    resp = messagebox.askyesnocancel(
        "Actualización disponible",
        f"Hay una nueva versión ({tag}).\nTú tienes la {VERSION_ACTUAL}.\n\n"
        "¿Descargar e instalar ahora?\n\n"
        "• Sí: descarga y reinicia la app\n"
        "• No: posponer 7 días\n"
        "• Cancelar: posponer hasta el próximo inicio")
    if resp is None:
        return
    if resp is False:
        _guardar_estado_update({
            "postergado_hasta": (datetime.now().timestamp() + 7 * 86400)
        })
        Toast(root, "Recordatorio pospuesto 7 días", "info")
        return

    tmp_dir = tempfile.gettempdir()
    nuevo_exe = os.path.join(tmp_dir, "ExpedientesMedicos_nuevo.exe")
    win_prog = VentanaProgresoDescarga(root, f"Descargando v{tag}")

    resultado = {"ok": False, "error": None}
    def _descargar():
        try:
            _descargar_con_progreso(exe_asset["browser_download_url"],
                                     nuevo_exe, win_prog)
            resultado["ok"] = True
        except Exception as e:
            resultado["error"] = str(e)

    t = threading.Thread(target=_descargar, daemon=True)
    t.start()

    def _esperar():
        if t.is_alive():
            root.after(100, _esperar)
        else:
            win_prog.destroy()
            if resultado["ok"]:
                _guardar_estado_update({"postergado_hasta": 0})
                _aplicar_actualizacion(nuevo_exe)
            else:
                messagebox.showerror("Error de descarga",
                                      f"No se pudo descargar:\n{resultado['error']}")
    _esperar()


# ==================== ESTILOS ====================
def configurar_estilos(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=PALETA["fondo"])

    style.configure("TFrame", background=PALETA["fondo"])
    style.configure("TLabel", background=PALETA["fondo"],
                    foreground=PALETA["texto"], font=F_NORMAL)
    style.configure("Primario.TButton", font=F_BOTON, padding=(14, 8),
                    background=PALETA["primario"], foreground="white", borderwidth=0)
    style.map("Primario.TButton", background=[("active", PALETA["primario_hov"])])
    style.configure("Exito.TButton", font=F_BOTON, padding=(14, 8),
                    background=PALETA["exito"], foreground="white", borderwidth=0)
    style.map("Exito.TButton", background=[("active", PALETA["exito_hov"])])
    style.configure("Peligro.TButton", font=F_BOTON, padding=(14, 8),
                    background=PALETA["peligro"], foreground="white", borderwidth=0)
    style.map("Peligro.TButton", background=[("active", PALETA["peligro_hov"])])
    style.configure("Advertencia.TButton", font=F_BOTON, padding=(14, 8),
                    background=PALETA["advertencia"], foreground="white", borderwidth=0)
    style.map("Advertencia.TButton", background=[("active", "#D97706")])
    style.configure("Secundario.TButton", font=F_BOTON, padding=(12, 7),
                    background=PALETA["tarjeta"], foreground=PALETA["texto"],
                    borderwidth=1, relief="solid")
    style.map("Secundario.TButton", background=[("active", PALETA["seleccion"])])

    style.configure("TEntry", padding=6, fieldbackground="white", borderwidth=1)
    style.configure("TCombobox", padding=6)
    style.configure("TNotebook", background=PALETA["fondo"], borderwidth=0)
    style.configure("TNotebook.Tab", font=F_NORMAL, padding=(18, 10),
                    background=PALETA["borde"], foreground=PALETA["texto_suave"])
    style.map("TNotebook.Tab",
              background=[("selected", PALETA["tarjeta"])],
              foreground=[("selected", PALETA["primario"])])
    style.configure("Treeview", font=F_NORMAL, rowheight=30,
                    background="white", fieldbackground="white", borderwidth=0)
    style.configure("Treeview.Heading", font=F_BOTON, padding=(8, 8),
                    background=PALETA["header"], foreground="white", relief="flat")
    style.map("Treeview", background=[("selected", PALETA["seleccion"])],
              foreground=[("selected", PALETA["texto"])])
    style.configure("Vertical.TScrollbar", background=PALETA["borde"],
                    troughcolor=PALETA["fondo"], borderwidth=0)


# ==================== HELPERS ====================
def crear_boton(parent, texto, comando, estilo="Primario.TButton", **kw):
    return ttk.Button(parent, text=texto, command=comando, style=estilo, **kw)


def crear_texto(parent, height=4, **kw):
    frame = tk.Frame(parent, bg=PALETA["borde"], bd=0, highlightthickness=0)
    txt = tk.Text(frame, height=height, wrap="word", font=F_NORMAL,
                  bg="white", fg=PALETA["texto"], relief="flat",
                  bd=0, padx=8, pady=6, insertbackground=PALETA["primario"],
                  highlightthickness=0, **kw)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    txt.pack(side="left", fill="both", expand=True, padx=1, pady=1)
    scroll.pack(side="right", fill="y")
    return frame, txt


def crear_entrada(parent, width=30, **kw):
    return ttk.Entry(parent, width=width, font=F_NORMAL, **kw)


def etiqueta_campo(parent, texto, requerido=False):
    txt = texto + (" *" if requerido else "")
    return tk.Label(parent, text=txt, bg=PALETA["tarjeta"],
                    fg=PALETA["texto"], font=F_LABEL, anchor="w")


def tamano_ventana(w_default, h_default, margen_x=60, margen_y=80):
    sw = tk._default_root.winfo_screenwidth() if tk._default_root else 1920
    sh = tk._default_root.winfo_screenheight() if tk._default_root else 1080
    return f"{min(w_default, sw - margen_x)}x{min(h_default, sh - margen_y)}"


# ==================== AUTOCOMPLETE ENTRY ====================
class AutocompleteEntry(ttk.Entry):
    def __init__(self, master, get_sugerencias, on_select=None, width=30, **kw):
        super().__init__(master, width=width, font=F_NORMAL, **kw)
        self.get_sugerencias = get_sugerencias
        self.on_select = on_select
        self._popup = None
        self._listbox = None
        self._resultados = []
        self.bind("<KeyRelease>", self._on_keyrelease)
        self.bind("<Down>", self._mover_abajo)
        self.bind("<Up>", self._mover_arriba)
        self.bind("<Return>", self._seleccionar_actual)
        self.bind("<Escape>", lambda e: self._cerrar_popup())
        self.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_out(self, event):
        self.after(180, self._cerrar_si_no_activo)

    def _cerrar_si_no_activo(self):
        if self._popup and self._popup.winfo_exists():
            try:
                foco = self.focus_get()
                if foco in (self._popup, self._listbox):
                    return
            except Exception:
                pass
            self._cerrar_popup()

    def _on_keyrelease(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab",
                            "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return
        texto = self.get().strip()
        if len(texto) < 1:
            self._cerrar_popup()
            return
        try:
            resultados = self.get_sugerencias(texto)
        except Exception:
            resultados = []
        if not resultados:
            self._cerrar_popup()
            return
        self._mostrar_popup(resultados)

    def _mostrar_popup(self, resultados):
        from tkinter import font as tkfont
        if self._popup is None or not self._popup.winfo_exists():
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.attributes("-topmost", True)
            self._popup.configure(bg=PALETA["borde"])
            frame = tk.Frame(self._popup, bg="white", bd=0)
            frame.pack(fill="both", expand=True, padx=1, pady=1)
            self._listbox = tk.Listbox(
                frame, font=(FUENTE, 11), bg="white", fg=PALETA["texto"],
                selectbackground=PALETA["seleccion"],
                selectforeground=PALETA["texto"],
                relief="flat", bd=0, activestyle="none",
                highlightthickness=0, exportselection=False)
            self._listbox.pack(fill="both", expand=True)
            self._listbox.bind("<Double-Button-1>", self._on_listbox_double)
        else:
            self._listbox.delete(0, tk.END)

        self._resultados = resultados[:8]
        for r in self._resultados:
            self._listbox.insert(tk.END, r[0])

        num = len(self._resultados)
        if num == 0:
            self._cerrar_popup()
            return
        self._listbox.configure(height=num)

        f = tkfont.Font(font=self._listbox.cget("font"))
        max_px = max(f.measure(r[0]) for r in self._resultados)
        w = max(self.winfo_width(), max_px + 40, 400)
        alto = num * 26 + 6
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        if y + alto > self.winfo_screenheight() - 40:
            y = self.winfo_rooty() - alto - 2
        if x + w > self.winfo_screenwidth():
            x = self.winfo_screenwidth() - w - 10
        self._popup.geometry(f"{w}x{alto}+{x}+{y}")
        self._popup.deiconify()
        self._popup.lift()

    def _on_listbox_double(self, event):
        sel = self._listbox.curselection()
        if sel:
            self._aplicar(self._resultados[sel[0]])

    def _mover_abajo(self, event):
        if self._listbox and self._popup and self._popup.winfo_exists():
            cur = self._listbox.curselection()
            idx = (cur[0] + 1) if cur else 0
            if idx < self._listbox.size():
                self._listbox.selection_clear(0, tk.END)
                self._listbox.selection_set(idx)
                self._listbox.see(idx)

    def _mover_arriba(self, event):
        if self._listbox and self._popup and self._popup.winfo_exists():
            cur = self._listbox.curselection()
            idx = max((cur[0] - 1), 0) if cur else 0
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)

    def _seleccionar_actual(self, event):
        if not (self._listbox and self._popup and self._popup.winfo_exists()):
            return
        cur = self._listbox.curselection()
        idx = cur[0] if cur else 0
        if idx < len(self._resultados):
            self._aplicar(self._resultados[idx])
            return "break"

    def _aplicar(self, resultado):
        self._cerrar_popup()
        if self.on_select:
            self.on_select(resultado)

    def _cerrar_popup(self):
        if self._popup:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
            self._listbox = None


# ==================== BASE DE DATOS ====================
def init_db():
    conn = conectar_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS expedientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        fecha_nacimiento TEXT,
        edad TEXT,
        sexo TEXT,
        enfermedades_cronicas TEXT,
        alergias TEXT,
        operaciones TEXT,
        consulta_por TEXT,
        sintomas TEXT,
        examenes_laboratorio TEXT,
        examenes_gabinete TEXT,
        diagnostico TEXT,
        receta TEXT,
        ultima_consulta TEXT,
        control_para TEXT,
        examenes_proxima_cita TEXT,
        fecha_registro TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS adjuntos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expediente_id INTEGER NOT NULL,
        tipo TEXT,
        nombre_archivo TEXT,
        ruta TEXT,
        FOREIGN KEY(expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS consultas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expediente_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        profesional TEXT,
        motivo TEXT,
        sintomas TEXT,
        diagnostico TEXT,
        cie10_codigo TEXT,
        cie10_descripcion TEXT,
        receta TEXT,
        notas TEXT,
        FOREIGN KEY(expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS medicamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        presentacion TEXT,
        stock INTEGER DEFAULT 0,
        precio REAL DEFAULT 0.0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cie10 (
        codigo TEXT PRIMARY KEY,
        descripcion TEXT NOT NULL,
        capitulo TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS receta_indicaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consulta_id INTEGER NOT NULL,
        codigo TEXT,
        nombre TEXT,
        presentacion TEXT,
        cantidad INTEGER,
        cada_horas INTEGER,
        por_dias INTEGER,
        indicaciones TEXT,
        FOREIGN KEY(consulta_id) REFERENCES consultas(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS plantillas_documentos (
        tipo TEXT PRIMARY KEY,
        contenido TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS configuracion (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS imagenes_documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT UNIQUE NOT NULL,
        ruta TEXT,
        posicion TEXT,
        ancho INTEGER,
        alto INTEGER
    )''')

    for col_def in [("proxima_cita", "TEXT"), ("indicaciones", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE consultas ADD COLUMN {col_def[0]} {col_def[1]}")
        except sqlite3.OperationalError:
            pass

    c.execute("CREATE INDEX IF NOT EXISTS idx_med_nombre ON medicamentos(nombre)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_med_codigo ON medicamentos(codigo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cie_desc ON cie10(descripcion)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cie_codigo ON cie10(codigo)")

    plantillas_default = {
        "incapacidad": (
            "INCAPACIDAD MÉDICA\n\nPaciente: {paciente}\nEdad: {edad}    Sexo: {sexo}\n"
            "Fecha: {fecha}\n\nPor medio de la presente se hace constar que el paciente\n"
            "recibió atención médica y requiere reposo por: ________________ días.\n\n"
            "Diagnóstico: {diagnostico}\n\nObservaciones:\n{notas}\n\n"
            "Médico responsable: {medico}\nFirma: _________________________"
        ),
        "constancia": (
            "CONSTANCIA DE CONSULTA\n\nPaciente: {paciente}\nEdad: {edad}    Sexo: {sexo}\n"
            "Fecha: {fecha}\n\nHago constar que el paciente asistió a consulta médica.\n\n"
            "Diagnóstico: {diagnostico}\n\nMédico responsable: {medico}\nFirma: _________________________"
        ),
        "recibo": (
            "RECIBO DE PAGO\n\nRecibí de: {paciente}\nLa cantidad de: $ ________________\n"
            "Por concepto de: Servicios médicos\nFecha: {fecha}\n\n"
            "Diagnóstico / Servicio: {diagnostico}\n\nReceta / Detalle:\n{receta}\n\n"
            "Atentamente,\n{medico}\nFirma: _________________________"
        ),
        "boleta": (
            "BOLETA DE EXÁMENES\n\nPaciente: {paciente}\nEdad: {edad}    Sexo: {sexo}\n"
            "Fecha: {fecha}\n\nSe solicitan los siguientes exámenes:\n{notas}\n\n"
            "Diagnóstico presuntivo: {diagnostico}\n\nMédico solicitante: {medico}\nFirma: _________________________"
        ),
        "receta": (
            "RECETA MÉDICA\n\nPaciente: {paciente}\nEdad: {edad}    Sexo: {sexo}\n"
            "Fecha: {fecha}\n\nRp.\n{receta}\n\nDiagnóstico: {diagnostico}\n\n"
            "Médico: {medico}\nFirma: _________________________"
        ),
    }
    for tipo, contenido in plantillas_default.items():
        c.execute("INSERT OR IGNORE INTO plantillas_documentos (tipo, contenido) VALUES (?,?)",
                  (tipo, contenido))

    config_default = {
        "nombre_clinica": "Clínica Médica",
        "direccion_clinica": "",
        "telefono_clinica": "",
        "email_clinica": "",
        "medico_default": "Dr. _________________________",
        "tamano_pagina": "letter",
        "mostrar_logo": "1",
        "mostrar_marca_agua": "1",
        "marca_agua_opacidad": "0.15",
        "mostrar_pie": "1",
        "texto_pie": "Documento generado por Sistema de Expedientes Médicos",
    }
    for clave, valor in config_default.items():
        c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?,?)",
                  (clave, valor))

    conn.commit()
    conn.close()


def calcular_edad(fecha_nac_str):
    try:
        fn = datetime.strptime(fecha_nac_str, "%Y-%m-%d")
        hoy = datetime.now()
        return str(hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day)))
    except Exception:
        return ""


def abrir_archivo_sistema(ruta):
    try:
        os.startfile(ruta)
    except AttributeError:
        subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", ruta])


def generar_codigo_medicamento(nombre: str) -> str:
    h = hashlib.sha256(nombre.strip().lower().encode("utf-8")).digest()
    return str(int.from_bytes(h[:8], byteorder="big"))[:12]


def sugerir_medicamentos(texto):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("""SELECT codigo, nombre, presentacion, stock, precio
                     FROM medicamentos
                     WHERE nombre LIKE ? OR codigo LIKE ?
                     ORDER BY nombre LIMIT 8""",
                  (f"%{texto}%", f"%{texto}%"))
        filas = c.fetchall()
    finally:
        conn.close()
    return [(f"{f[1]}  ·  {f[2]}  ·  Stock: {f[3]}", f"{f[1]}", f) for f in filas]


def sugerir_cie10(texto):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("""SELECT codigo, descripcion FROM cie10
                     WHERE codigo LIKE ? OR descripcion LIKE ?
                     ORDER BY codigo LIMIT 8""",
                  (f"%{texto}%", f"%{texto}%"))
        filas = c.fetchall()
    finally:
        conn.close()
    return [(f"{f[0]} — {f[1]}", f"{f[0]}", f) for f in filas]


def obtener_plantilla(tipo):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("SELECT contenido FROM plantillas_documentos WHERE tipo=?", (tipo,))
        fila = c.fetchone()
    finally:
        conn.close()
    return fila[0] if fila else ""


def get_config(clave, default=""):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,))
        fila = c.fetchone()
    finally:
        conn.close()
    return fila[0] if fila and fila[0] is not None else default


def set_config(clave, valor):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?,?)",
                  (clave, str(valor)))
        conn.commit()
    finally:
        conn.close()


def get_imagen(tipo):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("SELECT ruta, posicion, ancho, alto FROM imagenes_documentos WHERE tipo=?",
                  (tipo,))
        fila = c.fetchone()
    finally:
        conn.close()
    if fila and fila[0] and os.path.exists(fila[0]):
        return {"ruta": fila[0], "posicion": fila[1] or "centro",
                "ancho": fila[2] or 100, "alto": fila[3] or 100}
    return None


def set_imagen(tipo, ruta, posicion="centro", ancho=100, alto=100):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM imagenes_documentos WHERE tipo=?", (tipo,))
        c.execute("INSERT INTO imagenes_documentos (tipo, ruta, posicion, ancho, alto) VALUES (?,?,?,?,?)",
                  (tipo, ruta, posicion, ancho, alto))
        conn.commit()
    finally:
        conn.close()


def borrar_imagen(tipo):
    conn = conectar_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM imagenes_documentos WHERE tipo=?", (tipo,))
        conn.commit()
    finally:
        conn.close()


# ==================== TOAST ====================
class Toast:
    def __init__(self, root, mensaje, tipo="info", duracion=2500):
        colores = {"info": PALETA["primario"], "exito": PALETA["exito"],
                   "error": PALETA["peligro"], "aviso": PALETA["advertencia"]}
        self.ventana = tk.Toplevel(root)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        self.ventana.configure(bg=colores.get(tipo, PALETA["primario"]))
        frame = tk.Frame(self.ventana, bg=colores.get(tipo, PALETA["primario"]),
                         padx=20, pady=12)
        frame.pack()
        icono = {"info": "ℹ️", "exito": "✅", "error": "❌", "aviso": "⚠️"}.get(tipo, "ℹ️")
        tk.Label(frame, text=f"{icono}  {mensaje}", bg=colores.get(tipo),
                 fg="white", font=(FUENTE, 10, "bold")).pack()
        self.ventana.update_idletasks()
        w, h = self.ventana.winfo_width(), self.ventana.winfo_height()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.ventana.geometry(f"+{sw - w - 30}+{sh - h - 60}")
        root.after(duracion, self.ventana.destroy)


# ==================== PDF ====================
def generar_documento_pdf(tipo, datos, ruta_salida):
    try:
        from reportlab.lib.pagesizes import letter, A4, legal
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:
        messagebox.showerror("Error", "Falta 'reportlab'.\nInstálala con: pip install reportlab")
        return False

    nombre_clinica = get_config("nombre_clinica", "Clínica Médica")
    direccion = get_config("direccion_clinica", "")
    telefono = get_config("telefono_clinica", "")
    email = get_config("email_clinica", "")
    pie_texto = get_config("texto_pie", "")
    mostrar_logo = get_config("mostrar_logo", "1") == "1"
    mostrar_marca = get_config("mostrar_marca_agua", "1") == "1"
    opacidad_marca = float(get_config("marca_agua_opacidad", "0.15"))
    mostrar_pie = get_config("mostrar_pie", "1") == "1"
    tamano = get_config("tamano_pagina", "letter")

    paginas = {"letter": letter, "a4": A4, "legal": legal}
    page_size = paginas.get(tamano.lower(), letter)

    plantilla = obtener_plantilla(tipo) or "DOCUMENTO\n\n" + str(datos)
    try:
        texto = plantilla.format(**datos)
    except KeyError as e:
        messagebox.showerror("Error", f"Variable desconocida: {e}")
        return False

    c = canvas.Canvas(ruta_salida, pagesize=page_size)
    w, h = page_size

    if mostrar_marca:
        img_marca = get_imagen("marca_agua")
        if img_marca:
            try:
                c.saveState(); c.setFillAlpha(opacidad_marca)
                c.drawImage(img_marca["ruta"], (w - img_marca["ancho"]*3)/2,
                            (h - img_marca["alto"]*3)/2,
                            width=img_marca["ancho"]*3, height=img_marca["alto"]*3,
                            mask="auto", preserveAspectRatio=True, anchor="c")
                c.restoreState()
            except Exception:
                pass

    margen = 50
    margen_sup = h - 50

    if mostrar_logo:
        img = get_imagen("logo")
        if img:
            try:
                c.drawImage(img["ruta"], margen, margen_sup - img["alto"],
                            width=img["ancho"], height=img["alto"],
                            mask="auto", preserveAspectRatio=True)
            except Exception:
                pass

    y = margen_sup - 40
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0.12, 0.23, 0.54)
    c.drawCentredString(w/2, y, nombre_clinica)
    y -= 16
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    contacto = " | ".join([x for x in [direccion, telefono, email] if x])
    if contacto:
        c.drawCentredString(w/2, y, contacto)
        y -= 14
    c.setFillColorRGB(0, 0, 0)
    c.line(margen, y, w - margen, y)
    y -= 20

    ancho_util = w - 2 * margen
    c.setFont("Helvetica", 11)
    for parrafo in texto.split("\n"):
        palabras = parrafo.split(" ")
        linea = ""
        for palabra in palabras:
            prueba = (linea + " " + palabra).strip()
            if stringWidth(prueba, "Helvetica", 11) <= ancho_util:
                linea = prueba
            else:
                c.drawString(margen, y, linea); y -= 18
                linea = palabra
                if y < 100:
                    c.showPage(); c.setFont("Helvetica", 11); y = h - 60
        if linea:
            c.drawString(margen, y, linea); y -= 18
        if y < 100:
            c.showPage(); c.setFont("Helvetica", 11); y = h - 60

    sello = get_imagen("sello")
    if sello:
        try:
            c.drawImage(sello["ruta"], w - margen - sello["ancho"], 80,
                        width=sello["ancho"], height=sello["alto"],
                        mask="auto", preserveAspectRatio=True)
        except Exception:
            pass

    if mostrar_pie and pie_texto:
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawCentredString(w/2, 30, pie_texto)

    c.save()
    return True


# ==================== PREVIEW ====================
class VentanaPreview(tk.Toplevel):
    def __init__(self, master, texto, titulo="Previsualización"):
        super().__init__(master)
        self.texto = texto
        self.title(titulo)
        self.geometry(tamano_ventana(1000, 800))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=55)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="👁  " + titulo, bg=PALETA["header"], fg="white",
                 font=(FUENTE, 13, "bold")).pack(side="left", padx=20, pady=10)

        frame = tk.Frame(self, bg=PALETA["borde"])
        frame.pack(fill="both", expand=True, padx=20, pady=15)
        inner = tk.Frame(frame, bg="white"); inner.pack(fill="both", expand=True, padx=1, pady=1)
        txt = tk.Text(inner, wrap="word", font=("Courier New", 11),
                      bg="white", fg=PALETA["texto"], relief="flat",
                      bd=0, padx=20, pady=20)
        scroll = ttk.Scrollbar(inner, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        txt.insert("1.0", texto); txt.config(state="disabled")

        btns = tk.Frame(self, bg=PALETA["fondo"])
        btns.pack(fill="x", padx=20, pady=(0, 15))
        crear_boton(btns, "🖨  Guardar PDF", self._guardar, "Exito.TButton").pack(side="right", padx=5)
        crear_boton(btns, "✖  Cerrar", self.destroy, "Secundario.TButton").pack(side="right", padx=5)

    def _guardar(self):
        ruta = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")],
                                            initialfile="documento.pdf")
        if not ruta:
            return
        try:
            from reportlab.lib.pagesizes import letter, A4, legal
            from reportlab.pdfgen import canvas
            from reportlab.pdfbase.pdfmetrics import stringWidth
            tam = get_config("tamano_pagina", "letter")
            pags = {"letter": letter, "a4": A4, "legal": legal}
            size = pags.get(tam.lower(), letter)
            c = canvas.Canvas(ruta, pagesize=size)
            w, h = size
            margen = 50
            ancho_util = w - 2 * margen
            y = h - 60
            c.setFont("Helvetica", 11)
            for p in self.texto.split("\n"):
                linea = ""
                for palabra in p.split(" "):
                    prueba = (linea + " " + palabra).strip()
                    if stringWidth(prueba, "Helvetica", 11) <= ancho_util:
                        linea = prueba
                    else:
                        c.drawString(margen, y, linea); y -= 18
                        linea = palabra
                        if y < 100:
                            c.showPage(); c.setFont("Helvetica", 11); y = h - 60
                if linea:
                    c.drawString(margen, y, linea); y -= 18
                if y < 100:
                    c.showPage(); c.setFont("Helvetica", 11); y = h - 60
            c.save()
            Toast(self, f"PDF guardado", "exito")
        except Exception as e:
            messagebox.showerror("Error", str(e))


# ==================== PLANTILLAS ====================
class VentanaPlantillas(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("📝 Editar Plantillas")
        self.geometry(tamano_ventana(900, 650))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=60)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="📝  Editar Plantillas", bg=PALETA["header"],
                 fg="white", font=(FUENTE, 14, "bold")).pack(side="left", padx=20, pady=12)

        panel = tk.Frame(self, bg=PALETA["tarjeta"], padx=15, pady=10)
        panel.pack(fill="x", padx=15, pady=(10, 5))
        tk.Label(panel, text="Documento:", bg=PALETA["tarjeta"], font=F_LABEL).pack(side="left")
        self.tipos = {"Incapacidad": "incapacidad", "Constancia": "constancia",
                      "Recibo": "recibo", "Boleta": "boleta", "Receta": "receta"}
        self.combo = ttk.Combobox(panel, values=list(self.tipos.keys()),
                                  state="readonly", width=20, font=F_NORMAL)
        self.combo.current(0); self.combo.pack(side="left", padx=8)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._cargar())

        frame = tk.Frame(self, bg=PALETA["borde"])
        frame.pack(fill="both", expand=True, padx=15, pady=5)
        inner = tk.Frame(frame, bg="white"); inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.txt = tk.Text(inner, wrap="word", font=F_NORMAL, bg="white",
                           fg=PALETA["texto"], relief="flat", bd=0, padx=10, pady=10)
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        self.txt.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")

        btns = tk.Frame(self, bg=PALETA["fondo"]); btns.pack(fill="x", padx=15, pady=(5, 15))
        crear_boton(btns, "💾  Guardar", self._guardar, "Exito.TButton").pack(side="left", padx=5)
        crear_boton(btns, "✖  Cerrar", self.destroy, "Peligro.TButton").pack(side="right", padx=5)
        self._cargar()

    def _cargar(self):
        self.txt.delete("1.0", tk.END)
        self.txt.insert("1.0", obtener_plantilla(self.tipos[self.combo.get()]) or "")

    def _guardar(self):
        tipo = self.tipos[self.combo.get()]
        contenido = self.txt.get("1.0", tk.END).rstrip("\n")
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO plantillas_documentos (tipo, contenido) VALUES (?,?)",
                      (tipo, contenido))
            conn.commit()
        finally:
            conn.close()
        Toast(self, "Plantilla guardada", "exito")


# ==================== OPCIONES ====================
class VentanaOpciones(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("⚙️ Opciones")
        self.geometry(tamano_ventana(900, 700))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=60)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="⚙️  Opciones y Configuración", bg=PALETA["header"],
                 fg="white", font=(FUENTE, 14, "bold")).pack(side="left", padx=20, pady=12)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=15, pady=15)
        self._tab_clinica(nb); self._tab_docs(nb); self._tab_imgs(nb); self._tab_cats(nb)

        btns = tk.Frame(self, bg=PALETA["fondo"]); btns.pack(fill="x", padx=15, pady=(0, 15))
        crear_boton(btns, "💾  Guardar", self._guardar, "Exito.TButton").pack(side="right", padx=5)
        crear_boton(btns, "✖  Cerrar", self.destroy, "Peligro.TButton").pack(side="right", padx=5)

    def _tab_clinica(self, nb):
        tab = tk.Frame(nb, bg=PALETA["tarjeta"], padx=25, pady=20)
        nb.add(tab, text="🏥  Clínica")
        campos = [("Nombre de la clínica", "nombre_clinica"),
                  ("Dirección", "direccion_clinica"),
                  ("Teléfono", "telefono_clinica"),
                  ("Email", "email_clinica"),
                  ("Médico por defecto", "medico_default")]
        self.entries = {}
        for i, (label, clave) in enumerate(campos):
            etiqueta_campo(tab, label).grid(row=i, column=0, sticky="w", pady=5)
            e = crear_entrada(tab, width=55)
            e.insert(0, get_config(clave, ""))
            e.grid(row=i, column=1, sticky="w", padx=10, pady=5)
            self.entries[clave] = e
        etiqueta_campo(tab, "Tamaño PDF").grid(row=len(campos), column=0, sticky="w", pady=5)
        self.combo_pag = ttk.Combobox(tab, values=["letter", "a4", "legal"],
                                       state="readonly", width=20, font=F_NORMAL)
        self.combo_pag.set(get_config("tamano_pagina", "letter"))
        self.combo_pag.grid(row=len(campos), column=1, sticky="w", padx=10, pady=5)

        tk.Label(tab, text="").grid(row=len(campos) + 1, column=0, pady=10)
        crear_boton(tab, "🔄  Buscar actualizaciones",
                    lambda: verificar_actualizacion(self.master, manual=True),
                    "Primario.TButton").grid(row=len(campos) + 2, column=0,
                                              columnspan=2, sticky="w", pady=10)
        tk.Label(tab, text=f"Versión instalada: v{VERSION_ACTUAL}",
                 bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                 font=F_PEQUENA).grid(row=len(campos) + 3, column=0,
                                       columnspan=2, sticky="w")

    def _tab_docs(self, nb):
        tab = tk.Frame(nb, bg=PALETA["tarjeta"], padx=25, pady=20)
        nb.add(tab, text="📄  Documentos")
        self.var_logo = tk.BooleanVar(value=get_config("mostrar_logo", "1") == "1")
        self.var_marca = tk.BooleanVar(value=get_config("mostrar_marca_agua", "1") == "1")
        self.var_pie = tk.BooleanVar(value=get_config("mostrar_pie", "1") == "1")
        for texto, var in [("Mostrar logo", self.var_logo),
                           ("Mostrar marca de agua", self.var_marca),
                           ("Mostrar pie", self.var_pie)]:
            tk.Checkbutton(tab, text=texto, variable=var, bg=PALETA["tarjeta"],
                           font=F_NORMAL, anchor="w").pack(fill="x", pady=3)

        etiqueta_campo(tab, "Opacidad marca de agua (0.0-1.0)").pack(anchor="w", pady=(15, 5))
        self.e_op = crear_entrada(tab, width=10)
        self.e_op.insert(0, get_config("marca_agua_opacidad", "0.15"))
        self.e_op.pack(anchor="w")

        etiqueta_campo(tab, "Texto del pie").pack(anchor="w", pady=(15, 5))
        f, self.txt_pie = crear_texto(tab, height=3); f.pack(fill="x")
        self.txt_pie.insert("1.0", get_config("texto_pie", ""))

        crear_boton(tab, "📝  Editar plantillas", lambda: VentanaPlantillas(self),
                    "Primario.TButton").pack(anchor="w", pady=10)

    def _tab_imgs(self, nb):
        tab = tk.Frame(nb, bg=PALETA["tarjeta"], padx=25, pady=20)
        nb.add(tab, text="🖼  Imágenes")
        for tipo, titulo in [("logo", "Logo"), ("marca_agua", "Marca de agua"),
                              ("sello", "Sello / firma")]:
            frame = tk.LabelFrame(tab, text=titulo, bg=PALETA["tarjeta"],
                                  fg=PALETA["primario"], font=F_LABEL, padx=10, pady=10)
            frame.pack(fill="x", pady=8)
            img = get_imagen(tipo)
            tk.Label(frame, text="✅ Configurada" if img else "❌ Sin imagen",
                     bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                     font=F_PEQUENA).pack(side="left", padx=10)
            crear_boton(frame, "📂 Elegir", lambda t=tipo: self._elegir(t),
                        "Secundario.TButton").pack(side="left", padx=3)
            crear_boton(frame, "🗑 Quitar", lambda t=tipo: self._quitar(t),
                        "Peligro.TButton").pack(side="left", padx=3)

    def _elegir(self, tipo):
        ruta = filedialog.askopenfilename(filetypes=[("Imágenes", "*.png *.jpg *.jpeg")])
        if not ruta:
            return
        destino = os.path.join(RECURSOS_DIR, f"{tipo}_{os.path.basename(ruta)}")
        shutil.copy2(ruta, destino)
        dims = {"logo": (120, 60), "marca_agua": (300, 300), "sello": (120, 60)}
        a, h = dims.get(tipo, (100, 100))
        set_imagen(tipo, destino, "centro" if tipo == "marca_agua" else "izquierda", a, h)
        Toast(self, f"Imagen '{tipo}' configurada", "exito")

    def _quitar(self, tipo):
        if messagebox.askyesno("Confirmar", f"¿Quitar imagen '{tipo}'?"):
            borrar_imagen(tipo); Toast(self, "Imagen eliminada", "info")

    def _tab_cats(self, nb):
        tab = tk.Frame(nb, bg=PALETA["tarjeta"], padx=25, pady=20)
        nb.add(tab, text="📚  Catálogos")

        tk.Label(tab, text="CIE-10 (CSV: codigo,descripcion)",
                 bg=PALETA["tarjeta"], font=F_LABEL).pack(anchor="w")
        crear_boton(tab, "📥 Importar CIE-10", self._imp_cie,
                    "Primario.TButton").pack(anchor="w", pady=5)
        self.lbl_cie = tk.Label(tab, text="", bg=PALETA["tarjeta"],
                                fg=PALETA["texto_suave"], font=F_NORMAL)
        self.lbl_cie.pack(anchor="w", pady=10)

        tk.Frame(tab, height=2, bg=PALETA["borde"]).pack(fill="x", pady=15)

        tk.Label(tab, text="Medicamentos (CSV: nombre,presentacion,stock,precio)",
                 bg=PALETA["tarjeta"], font=F_LABEL).pack(anchor="w")
        crear_boton(tab, "💊 Importar medicamentos", self._imp_med,
                    "Primario.TButton").pack(anchor="w", pady=5)
        self.lbl_med = tk.Label(tab, text="", bg=PALETA["tarjeta"],
                                fg=PALETA["texto_suave"], font=F_NORMAL)
        self.lbl_med.pack(anchor="w", pady=10)

        self._act_cont()

    def _act_cont(self):
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM cie10"); n1 = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM medicamentos"); n2 = c.fetchone()[0]
        finally:
            conn.close()
        self.lbl_cie.config(text=f"{n1} códigos")
        self.lbl_med.config(text=f"{n2} medicamentos")

    def _imp_cie(self):
        ruta = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not ruta:
            return
        conn = None
        try:
            conn = conectar_db(); c = conn.cursor(); n = 0
            with open(ruta, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    cod = row.get("codigo") or row.get("code") or ""
                    desc = row.get("descripcion") or row.get("description") or ""
                    cap = row.get("capitulo") or row.get("chapter") or ""
                    if cod and desc:
                        c.execute("INSERT OR REPLACE INTO cie10 (codigo, descripcion, capitulo) VALUES (?,?,?)",
                                  (cod.strip(), desc.strip(), cap.strip()))
                        n += 1
            conn.commit()
            Toast(self, f"{n} códigos importados", "exito")
            self._act_cont()
        except Exception as e:
            if conn: conn.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            if conn: conn.close()

    def _imp_med(self):
        ruta = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not ruta:
            return
        conn = None
        try:
            conn = conectar_db(); c = conn.cursor(); n = 0
            with open(ruta, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    nombre = row.get("nombre") or row.get("name") or ""
                    if not nombre.strip():
                        continue
                    pres = row.get("presentacion") or row.get("presentation") or ""
                    try: stock = int(row.get("stock") or 0)
                    except ValueError: stock = 0
                    try: precio = float(row.get("precio") or row.get("price") or 0)
                    except ValueError: precio = 0.0
                    codigo = generar_codigo_medicamento(nombre)
                    c.execute("""INSERT OR IGNORE INTO medicamentos
                                 (codigo, nombre, presentacion, stock, precio) VALUES (?,?,?,?,?)""",
                              (codigo, nombre.strip(), pres.strip(), stock, precio))
                    n += 1
            conn.commit()
            Toast(self, f"{n} medicamentos procesados", "exito")
            self._act_cont()
        except Exception as e:
            if conn: conn.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            if conn: conn.close()

    def _guardar(self):
        for clave, entry in self.entries.items():
            set_config(clave, entry.get().strip())
        set_config("tamano_pagina", self.combo_pag.get())
        set_config("mostrar_logo", "1" if self.var_logo.get() else "0")
        set_config("mostrar_marca_agua", "1" if self.var_marca.get() else "0")
        set_config("mostrar_pie", "1" if self.var_pie.get() else "0")
        try:
            op = float(self.e_op.get())
            if not (0 <= op <= 1):
                raise ValueError
            set_config("marca_agua_opacidad", str(op))
        except ValueError:
            messagebox.showwarning("Aviso", "Opacidad debe ser 0.0 a 1.0"); return
        set_config("texto_pie", self.txt_pie.get("1.0", tk.END).strip())
        Toast(self, "Configuración guardada", "exito")


# ==================== FORMULARIO EXPEDIENTE ====================
class FormularioExpediente(tk.Toplevel):
    def __init__(self, master, expediente_id=None, on_save=None):
        super().__init__(master)
        self.expediente_id = expediente_id
        self.on_save = on_save
        self.archivos_nuevos = []
        self.archivos_guardados = []

        self.title("Editar Expediente" if expediente_id else "Nuevo Expediente")
        self.geometry(tamano_ventana(950, 800))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=70)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header,
                 text="✏️  Editar Expediente" if expediente_id else "➕  Nuevo Expediente",
                 bg=PALETA["header"], fg="white", font=F_TITULO).pack(side="left", padx=20)

        frame_btn = tk.Frame(self, bg=PALETA["fondo"], pady=10)
        frame_btn.pack(side="bottom", fill="x", padx=20)
        crear_boton(frame_btn, "✖  Cancelar", self._cancelar,
                    "Peligro.TButton").pack(side="right", padx=5)
        crear_boton(frame_btn, "🧹  Limpiar", self.limpiar,
                    "Advertencia.TButton").pack(side="right", padx=5)
        crear_boton(frame_btn, "💾  Guardar Expediente", self.guardar,
                    "Exito.TButton").pack(side="right", padx=5)

        cont = tk.Frame(self, bg=PALETA["fondo"])
        cont.pack(fill="both", expand=True, padx=20, pady=(15, 0))

        self.notebook = ttk.Notebook(cont)
        self.notebook.pack(fill="both", expand=True)

        self._tab_datos(); self._tab_antecedentes(); self._tab_examenes()
        self._tab_seguimiento(); self._tab_historial()

        if expediente_id:
            self._cargar_datos()

    def _cancelar(self):
        if messagebox.askyesno("Confirmar", "¿Cerrar sin guardar?"):
            self.destroy()

    def _tab_datos(self):
        tab = tk.Frame(self.notebook, bg=PALETA["tarjeta"], padx=25, pady=20)
        self.notebook.add(tab, text="👤  Datos Personales")
        etiqueta_campo(tab, "Nombre completo", requerido=True).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.entry_nombre = crear_entrada(tab, width=60)
        self.entry_nombre.grid(row=1, column=0, columnspan=4, sticky="we", pady=(0, 15))

        etiqueta_campo(tab, "Fecha de nacimiento", requerido=True).grid(row=2, column=0, sticky="w", pady=(0, 5))
        etiqueta_campo(tab, "Edad").grid(row=2, column=1, sticky="w", padx=(25, 0))
        etiqueta_campo(tab, "Sexo", requerido=True).grid(row=2, column=2, sticky="w", padx=(25, 0))

        self.cal_nac = tkcalendar.DateEntry(tab, date_pattern="yyyy-mm-dd", width=14,
                                             background=PALETA["primario"], foreground="white",
                                             borderwidth=0)
        self.cal_nac.grid(row=3, column=0, sticky="w")
        self.cal_nac.bind("<<DateEntrySelected>>", self._calc_edad)

        self.entry_edad = crear_entrada(tab, width=8, state="readonly")
        self.entry_edad.grid(row=3, column=1, sticky="w", padx=(25, 0))

        self.combo_sexo = ttk.Combobox(tab, values=["Masculino", "Femenino", "Otro"],
                                        state="readonly", width=18, font=F_NORMAL)
        self.combo_sexo.grid(row=3, column=2, sticky="w", padx=(25, 0))
        tab.columnconfigure(0, weight=1)

    def _calc_edad(self, event=None):
        self.entry_edad.config(state="normal")
        self.entry_edad.delete(0, tk.END)
        self.entry_edad.insert(0, calcular_edad(self.cal_nac.get()))
        self.entry_edad.config(state="readonly")

    def _tab_antecedentes(self):
        tab = tk.Frame(self.notebook, bg=PALETA["tarjeta"], padx=25, pady=20)
        self.notebook.add(tab, text="📋  Antecedentes")
        etiqueta_campo(tab, "Enfermedades crónicas").pack(anchor="w", pady=(0, 5))
        f, self.txt_cronicas = crear_texto(tab, height=4); f.pack(fill="x", pady=(0, 15))
        etiqueta_campo(tab, "Alergias").pack(anchor="w", pady=(0, 5))
        f, self.txt_alergias = crear_texto(tab, height=4); f.pack(fill="x", pady=(0, 15))
        etiqueta_campo(tab, "Historial de operaciones").pack(anchor="w", pady=(0, 5))
        f, self.txt_operaciones = crear_texto(tab, height=4); f.pack(fill="x")

    def _tab_examenes(self):
        tab = tk.Frame(self.notebook, bg=PALETA["tarjeta"], padx=25, pady=20)
        self.notebook.add(tab, text="🔬  Exámenes y Archivos")
        etiqueta_campo(tab, "Exámenes de laboratorio").pack(anchor="w", pady=(0, 5))
        f, self.txt_lab = crear_texto(tab, height=3); f.pack(fill="x", pady=(0, 15))
        etiqueta_campo(tab, "Exámenes de gabinete").pack(anchor="w", pady=(0, 5))
        f, self.txt_gabinete = crear_texto(tab, height=3); f.pack(fill="x", pady=(0, 15))
        etiqueta_campo(tab, "Archivos adjuntos").pack(anchor="w", pady=(0, 5))

        frame = tk.Frame(tab, bg=PALETA["borde"])
        frame.pack(fill="both", expand=True)
        inner = tk.Frame(frame, bg="white", padx=10, pady=10)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        b = tk.Frame(inner, bg="white"); b.pack(fill="x", pady=(0, 8))
        crear_boton(b, "📎 Adjuntar", self._adjuntar, "Secundario.TButton").pack(side="left", padx=(0, 5))
        crear_boton(b, "👁 Ver", self._abrir_arch, "Secundario.TButton").pack(side="left", padx=5)
        crear_boton(b, "🗑 Quitar", self._quitar_arch, "Secundario.TButton").pack(side="left", padx=5)

        self.tree_arch = ttk.Treeview(inner, columns=("tipo", "nombre", "ruta"),
                                       show="headings", height=6)
        for col in ("tipo", "nombre", "ruta"):
            self.tree_arch.heading(col, text=col.capitalize())
        self.tree_arch.column("tipo", width=80, anchor="center")
        self.tree_arch.column("nombre", width=250)
        self.tree_arch.column("ruta", width=380)
        self.tree_arch.pack(fill="both", expand=True)
        self.tree_arch.bind("<Double-1>", lambda e: self._abrir_arch())

    def _adjuntar(self):
        ruta = filedialog.askopenfilename(
            filetypes=[("Imágenes y PDF", "*.jpg *.jpeg *.png *.gif *.bmp *.pdf"),
                       ("Todos", "*.*")])
        if not ruta:
            return
        ext = os.path.splitext(ruta)[1].lower()
        tipo = "PDF" if ext == ".pdf" else "Imagen"
        self.archivos_nuevos.append((tipo, ruta))
        self.tree_arch.insert("", "end", values=(tipo, os.path.basename(ruta), ruta))

    def _abrir_arch(self):
        sel = self.tree_arch.selection()
        if not sel: return
        ruta = str(self.tree_arch.item(sel[0])["values"][2])
        if os.path.exists(ruta):
            abrir_archivo_sistema(ruta)

    def _quitar_arch(self):
        sel = self.tree_arch.selection()
        if not sel: return
        ruta = str(self.tree_arch.item(sel[0])["values"][2])
        self.tree_arch.delete(sel[0])
        self.archivos_nuevos = [(t, r) for t, r in self.archivos_nuevos if r != ruta]
        self.archivos_guardados = [a for a in self.archivos_guardados if a[2] != ruta]

    def _tab_seguimiento(self):
        tab = tk.Frame(self.notebook, bg=PALETA["tarjeta"], padx=25, pady=20)
        self.notebook.add(tab, text="📅  Seguimiento")

        tk.Label(tab,
                 text="Aquí puedes ver la última consulta y programar la próxima cita.",
                 bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                 font=F_PEQUENA).pack(anchor="w", pady=(0, 15))

        fila = tk.Frame(tab, bg=PALETA["tarjeta"]); fila.pack(fill="x", pady=(0, 20))

        c1 = tk.Frame(fila, bg=PALETA["tarjeta"]); c1.pack(side="left", padx=(0, 40))
        etiqueta_campo(c1, "Última consulta registrada").pack(anchor="w", pady=(0, 5))
        self.lbl_ultima = tk.Label(c1, text="—", bg=PALETA["tarjeta"],
                                    fg=PALETA["primario"], font=(FUENTE, 11, "bold"))
        self.lbl_ultima.pack(anchor="w")

        c2 = tk.Frame(fila, bg=PALETA["tarjeta"]); c2.pack(side="left")
        etiqueta_campo(c2, "Fecha de control / próxima cita").pack(anchor="w", pady=(0, 5))
        self.cal_control = tkcalendar.DateEntry(c2, date_pattern="yyyy-mm-dd", width=14,
                                                  background=PALETA["primario"], foreground="white",
                                                  borderwidth=0)
        self.cal_control.pack(anchor="w")

        etiqueta_campo(tab, "Exámenes / indicaciones para la próxima cita").pack(anchor="w", pady=(0, 5))
        f, self.txt_proximos = crear_texto(tab, height=8); f.pack(fill="both", expand=True)

    def _actualizar_ultima(self):
        if not self.expediente_id:
            self.lbl_ultima.config(text="Aún no hay consultas registradas")
            return
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT MAX(fecha) FROM consultas WHERE expediente_id=?",
                      (self.expediente_id,))
            u = c.fetchone()[0]
        finally:
            conn.close()
        self.lbl_ultima.config(text=u if u else "Aún no hay consultas registradas")

    def _tab_historial(self):
        tab = tk.Frame(self.notebook, bg=PALETA["tarjeta"], padx=25, pady=20)
        self.notebook.add(tab, text="🗂  Historial de Consultas")

        if not self.expediente_id:
            tk.Label(tab,
                     text="💡 Guarda primero el expediente para poder registrar consultas.",
                     bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                     font=F_NORMAL, justify="center").pack(pady=60)
            return

        b = tk.Frame(tab, bg=PALETA["tarjeta"]); b.pack(fill="x", pady=(0, 10))
        crear_boton(b, "➕ Nueva Consulta", self._nueva, "Exito.TButton").pack(side="left", padx=(0, 5))
        crear_boton(b, "👁 Ver/Editar", self._ver, "Primario.TButton").pack(side="left", padx=5)
        crear_boton(b, "🗑 Eliminar", self._eliminar, "Peligro.TButton").pack(side="left", padx=5)
        crear_boton(b, "🔄 Actualizar", self._cargar_consultas, "Secundario.TButton").pack(side="left", padx=5)

        frame = tk.Frame(tab, bg=PALETA["borde"])
        frame.pack(fill="both", expand=True)
        inner = tk.Frame(frame, bg="white"); inner.pack(fill="both", expand=True, padx=1, pady=1)

        cols = ("Fecha", "Profesional", "Motivo", "Diagnóstico", "CIE-10", "Próxima cita")
        self.tabla_cons = ttk.Treeview(inner, columns=cols, show="headings", height=15)
        for col in cols:
            self.tabla_cons.heading(col, text=col)
        self.tabla_cons.column("Fecha", width=130, anchor="center")
        self.tabla_cons.column("Profesional", width=160)
        self.tabla_cons.column("Motivo", width=200)
        self.tabla_cons.column("Diagnóstico", width=200)
        self.tabla_cons.column("CIE-10", width=100, anchor="center")
        self.tabla_cons.column("Próxima cita", width=120, anchor="center")
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.tabla_cons.yview)
        self.tabla_cons.configure(yscrollcommand=scroll.set)
        self.tabla_cons.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tabla_cons.bind("<Double-1>", lambda e: self._ver())

        self._cargar_consultas()

    def _cargar_consultas(self):
        if not self.expediente_id: return
        for r in self.tabla_cons.get_children():
            self.tabla_cons.delete(r)
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("""SELECT id, fecha, profesional, motivo, diagnostico,
                         cie10_codigo, proxima_cita
                         FROM consultas WHERE expediente_id=? ORDER BY fecha DESC""",
                      (self.expediente_id,))
            for fila in c.fetchall():
                self.tabla_cons.insert("", "end", iid=fila[0], values=fila[1:])
        finally:
            conn.close()
        self._actualizar_ultima()

    def _nueva(self):
        VentanaConsulta(self, self.expediente_id, on_save=self._cargar_consultas)

    def _ver(self):
        sel = self.tabla_cons.selection()
        if not sel:
            Toast(self, "Selecciona una consulta", "aviso"); return
        VentanaConsulta(self, self.expediente_id, consulta_id=int(sel[0]),
                        on_save=self._cargar_consultas)

    def _eliminar(self):
        sel = self.tabla_cons.selection()
        if not sel:
            Toast(self, "Selecciona una consulta", "aviso"); return
        if not messagebox.askyesno("Confirmar", "¿Eliminar esta consulta?"): return
        cid = int(sel[0])
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT codigo, cantidad FROM receta_indicaciones WHERE consulta_id=?", (cid,))
            for cod, cant in c.fetchall():
                c.execute("UPDATE medicamentos SET stock = stock + ? WHERE codigo = ?", (cant, cod))
            c.execute("DELETE FROM receta_indicaciones WHERE consulta_id=?", (cid,))
            c.execute("DELETE FROM consultas WHERE id=?", (cid,))
            conn.commit()
        finally:
            conn.close()
        self._cargar_consultas()
        Toast(self, "Consulta eliminada", "exito")

    def _cargar_datos(self):
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM expedientes WHERE id=?", (self.expediente_id,))
            fila = c.fetchone()
            if fila:
                c.execute("SELECT tipo, nombre_archivo, ruta FROM adjuntos WHERE expediente_id=?",
                          (self.expediente_id,))
                adj = c.fetchall()
            else:
                adj = []
        finally:
            conn.close()
        if not fila:
            messagebox.showerror("Error", "No encontrado"); self.destroy(); return
        (_, nombre, fnac, edad, sexo, cronicas, alergias, operaciones,
         _, _, lab, gabinete, _, _, _, control, proximos, _) = fila

        self.entry_nombre.insert(0, nombre or "")
        if fnac:
            try: self.cal_nac.set_date(datetime.strptime(fnac, "%Y-%m-%d").date())
            except Exception: pass
        self.entry_edad.config(state="normal")
        self.entry_edad.insert(0, edad or "")
        self.entry_edad.config(state="readonly")
        self.combo_sexo.set(sexo or "")

        self._set(self.txt_cronicas, cronicas)
        self._set(self.txt_alergias, alergias)
        self._set(self.txt_operaciones, operaciones)
        self._set(self.txt_lab, lab)
        self._set(self.txt_gabinete, gabinete)
        if control:
            try: self.cal_control.set_date(datetime.strptime(control, "%Y-%m-%d").date())
            except Exception: pass
        self._set(self.txt_proximos, proximos)

        for tipo, nom, ruta in adj:
            self.archivos_guardados.append((tipo, nom, ruta))
            self.tree_arch.insert("", "end", values=(tipo, nom, ruta))

        self._actualizar_ultima()

    @staticmethod
    def _set(w, v):
        w.delete("1.0", tk.END)
        if v: w.insert("1.0", v)

    def _get(self, w):
        return w.get("1.0", tk.END).strip()

    def limpiar(self):
        if not messagebox.askyesno("Confirmar", "¿Limpiar todos los campos?"): return
        self.entry_nombre.delete(0, tk.END)
        self.combo_sexo.set("")
        self.entry_edad.config(state="normal")
        self.entry_edad.delete(0, tk.END)
        self.entry_edad.config(state="readonly")
        for w in (self.txt_cronicas, self.txt_alergias, self.txt_operaciones,
                  self.txt_lab, self.txt_gabinete, self.txt_proximos):
            w.delete("1.0", tk.END)
        self.archivos_nuevos.clear(); self.archivos_guardados.clear()
        for i in self.tree_arch.get_children():
            self.tree_arch.delete(i)

    def guardar(self):
        nombre = self.entry_nombre.get().strip()
        if not nombre:
            messagebox.showwarning("Aviso", "El nombre es obligatorio")
            self.notebook.select(0); return

        datos = (
            nombre, self.cal_nac.get(), self.entry_edad.get(), self.combo_sexo.get(),
            self._get(self.txt_cronicas), self._get(self.txt_alergias),
            self._get(self.txt_operaciones),
            "", "", self._get(self.txt_lab), self._get(self.txt_gabinete),
            "", "",
            self._ultima_str(),
            self.cal_control.get(), self._get(self.txt_proximos),
        )
        conn = conectar_db()
        try:
            c = conn.cursor()
            if self.expediente_id:
                c.execute("""UPDATE expedientes SET
                    nombre=?, fecha_nacimiento=?, edad=?, sexo=?,
                    enfermedades_cronicas=?, alergias=?, operaciones=?,
                    consulta_por=?, sintomas=?, examenes_laboratorio=?,
                    examenes_gabinete=?, diagnostico=?, receta=?,
                    ultima_consulta=?, control_para=?, examenes_proxima_cita=?
                    WHERE id=?""", datos + (self.expediente_id,))
                eid = self.expediente_id
            else:
                c.execute("""INSERT INTO expedientes
                    (nombre, fecha_nacimiento, edad, sexo,
                     enfermedades_cronicas, alergias, operaciones,
                     consulta_por, sintomas, examenes_laboratorio,
                     examenes_gabinete, diagnostico, receta,
                     ultima_consulta, control_para, examenes_proxima_cita,
                     fecha_registro)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    datos + (datetime.now().strftime("%Y-%m-%d %H:%M"),))
                eid = c.lastrowid

            c.execute("SELECT ruta FROM adjuntos WHERE expediente_id=?", (eid,))
            rutas_bd = [r[0] for r in c.fetchall()]
            rutas_act = [a[2] for a in self.archivos_guardados]
            for r in rutas_bd:
                if r not in rutas_act:
                    c.execute("DELETE FROM adjuntos WHERE expediente_id=? AND ruta=?", (eid, r))

            carpeta = os.path.join(ADJUNTOS_DIR, f"exp_{eid}")
            os.makedirs(carpeta, exist_ok=True)
            for tipo, origen in self.archivos_nuevos:
                dest = os.path.join(carpeta, os.path.basename(origen))
                base, ext = os.path.splitext(dest)
                i = 1
                while os.path.exists(dest):
                    dest = f"{base}_{i}{ext}"; i += 1
                shutil.copy2(origen, dest)
                c.execute("INSERT INTO adjuntos (expediente_id, tipo, nombre_archivo, ruta) VALUES (?,?,?,?)",
                          (eid, tipo, os.path.basename(dest), dest))
            conn.commit()
            if self.on_save: self.on_save()
            self.destroy()
            Toast(self.master, "Expediente guardado", "exito")
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
        finally:
            conn.close()

    def _ultima_str(self):
        if not self.expediente_id: return ""
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT MAX(fecha) FROM consultas WHERE expediente_id=?",
                      (self.expediente_id,))
            return c.fetchone()[0] or ""
        finally:
            conn.close()


# ==================== VENTANA CONSULTA ====================
class VentanaConsulta(tk.Toplevel):
    def __init__(self, master, expediente_id, consulta_id=None, on_save=None):
        super().__init__(master)
        self.expediente_id = expediente_id
        self.consulta_id = consulta_id
        self.on_save = on_save
        self.medicamentos_receta = []
        self.med_seleccionado = None

        self.title("Editar Consulta" if consulta_id else "Nueva Consulta")
        self.geometry(tamano_ventana(900, 850))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=60)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="🩺  " + ("Editar Consulta" if consulta_id else "Nueva Consulta"),
                 bg=PALETA["header"], fg="white",
                 font=(FUENTE, 14, "bold")).pack(side="left", padx=20, pady=12)

        frame_btn = tk.Frame(self, bg=PALETA["fondo"], pady=10)
        frame_btn.pack(side="bottom", fill="x", padx=20)
        crear_boton(frame_btn, "✖  Cancelar", self.destroy,
                    "Peligro.TButton").pack(side="right", padx=5)
        crear_boton(frame_btn, "💾  Guardar Consulta", self.guardar,
                    "Exito.TButton").pack(side="right", padx=5)

        main = tk.Frame(self, bg=PALETA["fondo"])
        main.pack(fill="both", expand=True, padx=20, pady=(15, 0))

        canvas = tk.Canvas(main, bg=PALETA["tarjeta"], highlightthickness=0)
        scroll = ttk.Scrollbar(main, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=PALETA["tarjeta"], padx=25, pady=20)
        bw = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(bw, width=e.width))
        def _on_mousewheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except tk.TclError:
                pass

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        etiqueta_campo(body, "Fecha de consulta").pack(anchor="w", pady=(0, 5))
        self.cal_fecha = tkcalendar.DateEntry(body, date_pattern="yyyy-mm-dd", width=14,
                                                background=PALETA["primario"], foreground="white",
                                                borderwidth=0)
        self.cal_fecha.pack(anchor="w", pady=(0, 15))

        etiqueta_campo(body, "Profesional que atendió").pack(anchor="w", pady=(0, 5))
        self.entry_prof = crear_entrada(body, width=50); self.entry_prof.pack(fill="x", pady=(0, 15))

        etiqueta_campo(body, "Motivo de consulta (sugerencias CIE-10)").pack(anchor="w", pady=(0, 5))
        self.entry_motivo = AutocompleteEntry(body, get_sugerencias=sugerir_cie10,
                                                on_select=self._motivo_sel, width=60)
        self.entry_motivo.pack(fill="x", pady=(0, 15))

        etiqueta_campo(body, "Síntomas").pack(anchor="w", pady=(0, 5))
        f, self.txt_sintomas = crear_texto(body, height=2); f.pack(fill="x", pady=(0, 15))

        etiqueta_campo(body, "Diagnóstico").pack(anchor="w", pady=(0, 5))
        f, self.txt_diagnostico = crear_texto(body, height=2); f.pack(fill="x", pady=(0, 10))

        fc = tk.Frame(body, bg=PALETA["tarjeta"]); fc.pack(fill="x", pady=(0, 15))
        tk.Label(fc, text="CIE-10:", bg=PALETA["tarjeta"], font=F_LABEL).pack(side="left")
        self.entry_cie_cod = AutocompleteEntry(fc, get_sugerencias=sugerir_cie10,
                                                 on_select=self._cie_sel, width=20)
        self.entry_cie_cod.pack(side="left", padx=5)
        self.entry_cie_desc = crear_entrada(fc, width=45)
        self.entry_cie_desc.pack(side="left", padx=5)

        etiqueta_campo(body, "Receta").pack(anchor="w", pady=(0, 5))
        fr = tk.Frame(body, bg=PALETA["tarjeta"]); fr.pack(fill="x", pady=(0, 10))

        bm = tk.Frame(fr, bg=PALETA["tarjeta"]); bm.pack(fill="x", pady=(0, 5))
        tk.Label(bm, text="🔎 Medicamento:", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(0, 5))
        self.entry_med = AutocompleteEntry(bm, get_sugerencias=sugerir_medicamentos,
                                             on_select=self._med_sel, width=32)
        self.entry_med.pack(side="left", padx=5)
        tk.Label(bm, text="Cant:", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(10, 5))
        self.entry_cant = crear_entrada(bm, width=5)
        self.entry_cant.insert(0, "1"); self.entry_cant.pack(side="left", padx=5)

        bi = tk.Frame(fr, bg=PALETA["tarjeta"]); bi.pack(fill="x", pady=(0, 5))
        tk.Label(bi, text="Cada", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(0, 5))
        self.entry_cada = crear_entrada(bi, width=6)
        self.entry_cada.insert(0, "8"); self.entry_cada.pack(side="left", padx=5)
        tk.Label(bi, text="horas, por", bg=PALETA["tarjeta"],
                 font=F_NORMAL).pack(side="left", padx=(0, 5))
        self.entry_dias = crear_entrada(bi, width=6)
        self.entry_dias.insert(0, "7"); self.entry_dias.pack(side="left", padx=5)
        tk.Label(bi, text="días", bg=PALETA["tarjeta"],
                 font=F_NORMAL).pack(side="left", padx=(0, 15))
        crear_boton(bi, "➕ Agregar a receta", self._agregar_med,
                    "Exito.TButton").pack(side="left", padx=5)

        bie = tk.Frame(fr, bg=PALETA["tarjeta"]); bie.pack(fill="x", pady=(0, 5))
        tk.Label(bie, text="Indicaciones extra:", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(0, 5))
        self.entry_indic = crear_entrada(bie, width=55)
        self.entry_indic.pack(side="left", padx=5, fill="x", expand=True)

        ft = tk.Frame(fr, bg=PALETA["borde"]); ft.pack(fill="x")
        it = tk.Frame(ft, bg="white"); it.pack(fill="x", padx=1, pady=1)

        cols = ("codigo", "nombre", "presentacion", "cantidad", "indicacion")
        self.tabla_rec = ttk.Treeview(it, columns=cols, show="headings", height=6)
        self.tabla_rec.heading("codigo", text="Código")
        self.tabla_rec.heading("nombre", text="Medicamento")
        self.tabla_rec.heading("presentacion", text="Presentación")
        self.tabla_rec.heading("cantidad", text="Cant.")
        self.tabla_rec.heading("indicacion", text="Indicación")
        self.tabla_rec.column("codigo", width=100, anchor="center")
        self.tabla_rec.column("nombre", width=200)
        self.tabla_rec.column("presentacion", width=120)
        self.tabla_rec.column("cantidad", width=60, anchor="center")
        self.tabla_rec.column("indicacion", width=280)
        self.tabla_rec.pack(fill="x")

        br = tk.Frame(fr, bg=PALETA["tarjeta"]); br.pack(fill="x", pady=(5, 0))
        crear_boton(br, "🗑 Quitar seleccionado", self._quitar_med,
                    "Peligro.TButton").pack(side="left")

        tk.Label(fr, text="💡 Escribe el medicamento, elige, ajusta cantidad e intervalo, y pulsa 'Agregar a receta'.",
                 bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                 font=F_PEQUENA).pack(anchor="w", pady=(5, 0))

        etiqueta_campo(body, "Receta final (se autorellena)").pack(anchor="w", pady=(10, 5))
        f, self.txt_receta = crear_texto(body, height=6); f.pack(fill="x", pady=(0, 15))

        etiqueta_campo(body, "Notas adicionales").pack(anchor="w", pady=(0, 5))
        f, self.txt_notas = crear_texto(body, height=3); f.pack(fill="x", pady=(0, 10))

        fp = tk.Frame(body, bg=PALETA["tarjeta"]); fp.pack(fill="x", pady=(15, 5))
        tk.Label(fp, text="📅 Próxima cita:", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(0, 10))
        self.cal_prox = tkcalendar.DateEntry(fp, date_pattern="yyyy-mm-dd", width=14,
                                               background=PALETA["primario"], foreground="white",
                                               borderwidth=0)
        self.cal_prox.pack(side="left")
        tk.Label(fp, text="(opcional, aparece en el historial del paciente)",
                 bg=PALETA["tarjeta"], fg=PALETA["texto_suave"],
                 font=F_PEQUENA).pack(side="left", padx=10)

        fd = tk.Frame(body, bg=PALETA["tarjeta"]); fd.pack(fill="x", pady=(10, 5))
        tk.Label(fd, text="Generar:", bg=PALETA["tarjeta"],
                 font=F_LABEL).pack(side="left", padx=(0, 10))
        for texto, tipo in [("📄 Incapacidad", "incapacidad"),
                             ("📋 Constancia", "constancia"),
                             ("🧾 Recibo", "recibo"),
                             ("🔬 Boleta", "boleta"),
                             ("💊 Receta", "receta")]:
            crear_boton(fd, texto, lambda t=tipo: self._generar(t),
                        "Secundario.TButton").pack(side="left", padx=3)

        if consulta_id:
            self._cargar()

    def _motivo_sel(self, r):
        cod, desc = r[2][0], r[2][1]
        self.entry_motivo.delete(0, tk.END); self.entry_motivo.insert(0, desc)
        self.entry_cie_cod.delete(0, tk.END); self.entry_cie_cod.insert(0, cod)
        self.entry_cie_desc.delete(0, tk.END); self.entry_cie_desc.insert(0, desc)

    def _cie_sel(self, r):
        cod, desc = r[2][0], r[2][1]
        self.entry_cie_cod.delete(0, tk.END); self.entry_cie_cod.insert(0, cod)
        self.entry_cie_desc.delete(0, tk.END); self.entry_cie_desc.insert(0, desc)

    def _med_sel(self, r):
        datos = r[2]
        self.med_seleccionado = datos
        self.entry_med.delete(0, tk.END)
        self.entry_med.insert(0, datos[1])
        self.tabla_rec.delete(*self.tabla_rec.get_children())
        self.tabla_rec.insert("", "end", values=(datos[0], datos[1], datos[2], "-", "—"))
        self.entry_cant.focus_set()
        self.entry_cant.select_range(0, tk.END)

    def _agregar_med(self):
        if not self.med_seleccionado:
            Toast(self, "Escribe y elige un medicamento de la lista", "aviso"); return

        cod, nombre, pres, stock, precio = self.med_seleccionado
        try:
            cant = int(self.entry_cant.get())
            cada = int(self.entry_cada.get())
            dias = int(self.entry_dias.get())
            if cant <= 0 or cada <= 0 or dias <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Cantidad, intervalo y días deben ser números positivos")
            return

        extra = self.entry_indic.get().strip()

        encontrado = False
        for i, item in enumerate(self.medicamentos_receta):
            if item[0] == cod:
                nueva = item[3] + cant
                if nueva > int(stock):
                    messagebox.showerror("Sin stock",
                                         f"Solo hay {stock} de {nombre}.\nYa tienes {item[3]}.")
                    return
                self.medicamentos_receta[i] = (cod, nombre, pres, nueva, cada, dias, extra)
                encontrado = True
                break

        if not encontrado:
            if cant > int(stock):
                messagebox.showerror("Sin stock", f"Solo hay {stock} de {nombre}"); return
            self.medicamentos_receta.append((cod, nombre, pres, cant, cada, dias, extra))

        self._refrescar()
        self._actualizar_txt()

        self.entry_med.delete(0, tk.END)
        self.entry_cant.delete(0, tk.END); self.entry_cant.insert(0, "1")
        self.entry_cada.delete(0, tk.END); self.entry_cada.insert(0, "8")
        self.entry_dias.delete(0, tk.END); self.entry_dias.insert(0, "7")
        self.entry_indic.delete(0, tk.END)
        self.med_seleccionado = None

    def _quitar_med(self):
        sel = self.tabla_rec.selection()
        if not sel: return
        idx = self.tabla_rec.index(sel[0])
        self.medicamentos_receta.pop(idx)
        self._refrescar(); self._actualizar_txt()

    def _refrescar(self):
        self.tabla_rec.delete(*self.tabla_rec.get_children())
        for cod, nom, pres, cant, cada, dias, extra in self.medicamentos_receta:
            ind = f"cada {cada}h por {dias}d"
            if extra: ind += f" — {extra}"
            self.tabla_rec.insert("", "end", values=(cod, nom, pres, cant, ind))

    def _actualizar_txt(self):
        self.txt_receta.delete("1.0", tk.END)
        for cod, nom, pres, cant, cada, dias, extra in self.medicamentos_receta:
            linea = f"• {nom} {pres} — {cant} unidad(es), cada {cada} horas por {dias} días"
            if extra: linea += f" ({extra})"
            self.txt_receta.insert(tk.END, linea + "\n")

    def _cargar(self):
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("""SELECT fecha, profesional, motivo, sintomas, diagnostico,
                         cie10_codigo, cie10_descripcion, receta, notas, proxima_cita
                         FROM consultas WHERE id=?""", (self.consulta_id,))
            fila = c.fetchone()
            c.execute("""SELECT codigo, nombre, presentacion, cantidad,
                         cada_horas, por_dias, indicaciones
                         FROM receta_indicaciones WHERE consulta_id=?""",
                       (self.consulta_id,))
            meds = c.fetchall()
        finally:
            conn.close()
        if not fila: return
        fecha, prof, motivo, sintomas, diag, cc, cd, receta, notas, prox = fila
        try: self.cal_fecha.set_date(datetime.strptime(fecha, "%Y-%m-%d").date())
        except Exception: pass
        self.entry_prof.insert(0, prof or "")
        self.entry_motivo.insert(0, motivo or "")
        self.txt_sintomas.insert("1.0", sintomas or "")
        self.txt_diagnostico.insert("1.0", diag or "")
        self.entry_cie_cod.insert(0, cc or "")
        self.entry_cie_desc.insert(0, cd or "")
        self.txt_notas.insert("1.0", notas or "")
        if prox:
            try: self.cal_prox.set_date(datetime.strptime(prox, "%Y-%m-%d").date())
            except Exception: pass
        self.medicamentos_receta = [(cod, nom, pres, cant, cada or 8, dias or 7, extra or "")
                                     for cod, nom, pres, cant, cada, dias, extra in meds]
        self._refrescar()
        self.txt_receta.delete("1.0", tk.END)
        if receta: self.txt_receta.insert("1.0", receta)

    def _generar(self, tipo):
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT nombre, edad, sexo FROM expedientes WHERE id=?",
                      (self.expediente_id,))
            fila = c.fetchone()
        finally:
            conn.close()
        if not fila: return
        nom, edad, sexo = fila
        datos = {
            "paciente": nom or "—", "edad": edad or "—", "sexo": sexo or "—",
            "fecha": self.cal_fecha.get(),
            "diagnostico": self.txt_diagnostico.get("1.0", tk.END).strip() or "—",
            "receta": self.txt_receta.get("1.0", tk.END).strip() or "—",
            "notas": self.txt_notas.get("1.0", tk.END).strip() or "—",
            "medico": self.entry_prof.get().strip() or get_config("medico_default", "—"),
        }
        plantilla = obtener_plantilla(tipo)
        if not plantilla: return
        try:
            texto = plantilla.format(**datos)
        except KeyError as e:
            messagebox.showerror("Error", f"Variable desconocida: {e}"); return
        VentanaPreview(self, texto, titulo=f"Previsualización - {tipo.capitalize()}")

    def guardar(self):
        datos = (
            self.expediente_id, self.cal_fecha.get(),
            self.entry_prof.get().strip(), self.entry_motivo.get().strip(),
            self.txt_sintomas.get("1.0", tk.END).strip(),
            self.txt_diagnostico.get("1.0", tk.END).strip(),
            self.entry_cie_cod.get().strip(), self.entry_cie_desc.get().strip(),
            self.txt_receta.get("1.0", tk.END).strip(),
            self.txt_notas.get("1.0", tk.END).strip(),
            self.cal_prox.get(),
        )
        conn = conectar_db()
        try:
            c = conn.cursor()
            if self.consulta_id:
                c.execute("""UPDATE consultas SET
                    expediente_id=?, fecha=?, profesional=?, motivo=?, sintomas=?,
                    diagnostico=?, cie10_codigo=?, cie10_descripcion=?, receta=?, notas=?,
                    proxima_cita=?
                    WHERE id=?""", datos + (self.consulta_id,))
                cid = self.consulta_id
                c.execute("SELECT codigo, cantidad FROM receta_indicaciones WHERE consulta_id=?", (cid,))
                for cod, cant in c.fetchall():
                    c.execute("UPDATE medicamentos SET stock = stock + ? WHERE codigo = ?", (cant, cod))
                c.execute("DELETE FROM receta_indicaciones WHERE consulta_id=?", (cid,))
            else:
                c.execute("""INSERT INTO consultas
                    (expediente_id, fecha, profesional, motivo, sintomas,
                     diagnostico, cie10_codigo, cie10_descripcion, receta, notas,
                     proxima_cita)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""", datos)
                cid = c.lastrowid

            for cod, nom, pres, cant, cada, dias, extra in self.medicamentos_receta:
                c.execute("""INSERT INTO receta_indicaciones
                             (consulta_id, codigo, nombre, presentacion, cantidad,
                              cada_horas, por_dias, indicaciones)
                             VALUES (?,?,?,?,?,?,?,?)""",
                          (cid, cod, nom, pres, cant, cada, dias, extra))
                c.execute("UPDATE medicamentos SET stock = stock - ? WHERE codigo = ?",
                          (cant, cod))
            conn.commit()
            if self.on_save: self.on_save()
            self.destroy()
            Toast(self.master, "Consulta guardada", "exito")
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
        finally:
            conn.close()


# ==================== MEDICAMENTOS ====================
class VentanaMedicamentos(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("💊 Medicamentos")
        self.geometry(tamano_ventana(950, 650))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=60)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="💊  Almacén de Medicamentos", bg=PALETA["header"],
                 fg="white", font=(FUENTE, 14, "bold")).pack(side="left", padx=20, pady=12)

        form = tk.Frame(self, bg=PALETA["tarjeta"], padx=20, pady=15)
        form.pack(fill="x", padx=20, pady=15)

        tk.Label(form, text="Nombre:", bg=PALETA["tarjeta"], font=F_LABEL).grid(row=0, column=0, sticky="w")
        self.e_nom = ttk.Entry(form, width=32, font=F_NORMAL); self.e_nom.grid(row=0, column=1, padx=8, pady=5)
        tk.Label(form, text="Presentación:", bg=PALETA["tarjeta"], font=F_LABEL).grid(row=0, column=2, sticky="w")
        self.e_pres = ttk.Entry(form, width=22, font=F_NORMAL); self.e_pres.grid(row=0, column=3, padx=8, pady=5)
        tk.Label(form, text="Stock:", bg=PALETA["tarjeta"], font=F_LABEL).grid(row=1, column=0, sticky="w")
        self.e_stock = ttk.Entry(form, width=10, font=F_NORMAL)
        self.e_stock.insert(0, "0"); self.e_stock.grid(row=1, column=1, padx=8, pady=5, sticky="w")
        tk.Label(form, text="Precio:", bg=PALETA["tarjeta"], font=F_LABEL).grid(row=1, column=2, sticky="w")
        self.e_precio = ttk.Entry(form, width=12, font=F_NORMAL)
        self.e_precio.insert(0, "0.00"); self.e_precio.grid(row=1, column=3, padx=8, pady=5, sticky="w")
        crear_boton(form, "➕ Agregar/Actualizar", self.agregar,
                    "Exito.TButton").grid(row=2, column=1, sticky="w", pady=10)
        crear_boton(form, "🗑 Eliminar", self.eliminar,
                    "Peligro.TButton").grid(row=2, column=2, sticky="w", pady=10)

        b = tk.Frame(self, bg=PALETA["fondo"]); b.pack(fill="x", padx=20, pady=(0, 5))
        tk.Label(b, text="🔍 Buscar:", bg=PALETA["fondo"], font=F_LABEL).pack(side="left")
        self.e_filtro = ttk.Entry(b, width=40, font=F_NORMAL); self.e_filtro.pack(side="left", padx=5)
        self.e_filtro.bind("<KeyRelease>", lambda e: self.cargar())
        self.lbl_c = tk.Label(b, text="", bg=PALETA["fondo"],
                               fg=PALETA["texto_suave"], font=F_PEQUENA)
        self.lbl_c.pack(side="right", padx=10)

        frame = tk.Frame(self, bg=PALETA["borde"])
        frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        inner = tk.Frame(frame, bg="white"); inner.pack(fill="both", expand=True, padx=1, pady=1)

        cols = ("Código", "Nombre", "Presentación", "Stock", "Precio")
        self.tabla = ttk.Treeview(inner, columns=cols, show="headings", height=14)
        for col in cols:
            self.tabla.heading(col, text=col)
        self.tabla.column("Código", width=130, anchor="center")
        self.tabla.column("Nombre", width=340)
        self.tabla.column("Presentación", width=170)
        self.tabla.column("Stock", width=80, anchor="center")
        self.tabla.column("Precio", width=90, anchor="center")
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tabla.bind("<<TreeviewSelect>>", self._al_sel)
        self.cargar()

    def _al_sel(self, event=None):
        sel = self.tabla.selection()
        if not sel: return
        v = self.tabla.item(sel[0])["values"]
        self.e_nom.delete(0, tk.END); self.e_nom.insert(0, v[1])
        self.e_pres.delete(0, tk.END)
        if v[2]: self.e_pres.insert(0, v[2])
        self.e_stock.delete(0, tk.END); self.e_stock.insert(0, "0")
        self.e_precio.delete(0, tk.END); self.e_precio.insert(0, str(v[4]))

    def cargar(self):
        for r in self.tabla.get_children():
            self.tabla.delete(r)
        f = self.e_filtro.get().strip()
        conn = conectar_db()
        try:
            c = conn.cursor()
            if f:
                c.execute("""SELECT codigo, nombre, presentacion, stock, precio FROM medicamentos
                             WHERE nombre LIKE ? OR codigo LIKE ? OR presentacion LIKE ?
                             ORDER BY nombre""", (f"%{f}%", f"%{f}%", f"%{f}%"))
            else:
                c.execute("SELECT codigo, nombre, presentacion, stock, precio FROM medicamentos ORDER BY nombre")
            filas = c.fetchall()
        finally:
            conn.close()
        for f_ in filas:
            self.tabla.insert("", "end", values=f_)
        self.lbl_c.config(text=f"{len(filas)} medicamento(s)")

    def agregar(self):
        nombre = self.e_nom.get().strip()
        if not nombre:
            messagebox.showwarning("Aviso", "El nombre es obligatorio"); return
        pres = self.e_pres.get().strip()
        try:
            stock = int(self.e_stock.get()); precio = float(self.e_precio.get())
        except ValueError:
            messagebox.showerror("Error", "Stock entero, precio número"); return
        if stock <= 0:
            messagebox.showwarning("Aviso", "Stock debe ser > 0"); return

        cod = generar_codigo_medicamento(nombre)
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("SELECT stock FROM medicamentos WHERE codigo=?", (cod,))
            ex = c.fetchone()
            if ex:
                c.execute("""UPDATE medicamentos SET stock = stock + ?,
                             presentacion = CASE WHEN ? != '' THEN ? ELSE presentacion END,
                             precio = CASE WHEN ? > 0 THEN ? ELSE precio END
                             WHERE codigo = ?""",
                          (stock, pres, pres, precio, precio, cod))
                conn.commit()
                Toast(self, f"Stock actualizado → {ex[0] + stock}", "exito")
            else:
                c.execute("""INSERT INTO medicamentos (codigo, nombre, presentacion, stock, precio)
                             VALUES (?,?,?,?,?)""", (cod, nombre, pres, stock, precio))
                conn.commit()
                Toast(self, f"Agregado. Código: {cod}", "exito")
            self.e_nom.delete(0, tk.END); self.e_pres.delete(0, tk.END)
            self.e_stock.delete(0, tk.END); self.e_stock.insert(0, "0")
            self.e_precio.delete(0, tk.END); self.e_precio.insert(0, "0.00")
            self.cargar()
        finally:
            conn.close()

    def eliminar(self):
        sel = self.tabla.selection()
        if not sel: return
        cod = self.tabla.item(sel[0])["values"][0]
        if not messagebox.askyesno("Confirmar", "¿Eliminar medicamento?"): return
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("DELETE FROM medicamentos WHERE codigo=?", (cod,))
            conn.commit()
        finally:
            conn.close()
        self.cargar()


# ==================== CIE-10 ====================
class VentanaCIE10(tk.Toplevel):
    def __init__(self, master, callback=None):
        super().__init__(master)
        self.callback = callback
        self.title("🔍 CIE-10")
        self.geometry(tamano_ventana(750, 550))
        self.configure(bg=PALETA["fondo"])
        self.transient(master); self.grab_set()

        header = tk.Frame(self, bg=PALETA["header"], height=60)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="🔍  Catálogo CIE-10", bg=PALETA["header"],
                 fg="white", font=(FUENTE, 14, "bold")).pack(side="left", padx=20, pady=12)

        f = tk.Frame(self, bg=PALETA["fondo"]); f.pack(fill="x", padx=20, pady=15)
        tk.Label(f, text="Buscar:", bg=PALETA["fondo"], font=F_LABEL).pack(side="left")
        self.e = ttk.Entry(f, width=45, font=F_NORMAL); self.e.pack(side="left", padx=5)
        self.e.bind("<KeyRelease>", lambda ev: self.buscar())

        fr = tk.Frame(self, bg=PALETA["borde"])
        fr.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        inner = tk.Frame(fr, bg="white"); inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.tabla = ttk.Treeview(inner, columns=("Código", "Descripción"), show="headings")
        self.tabla.heading("Código", text="Código")
        self.tabla.heading("Descripción", text="Descripción")
        self.tabla.column("Código", width=110, anchor="center")
        self.tabla.column("Descripción", width=580)
        self.tabla.pack(fill="both", expand=True)
        self.tabla.bind("<Double-1>", lambda ev: self.sel())

        fb = tk.Frame(self, bg=PALETA["fondo"]); fb.pack(fill="x", padx=20, pady=(0, 15))
        crear_boton(fb, "✔ Seleccionar", self.sel, "Exito.TButton").pack(side="right", padx=5)
        crear_boton(fb, "Cerrar", self.destroy, "Secundario.TButton").pack(side="right", padx=5)
        self.buscar()

    def buscar(self):
        for r in self.tabla.get_children():
            self.tabla.delete(r)
        f = self.e.get().strip()
        conn = conectar_db()
        try:
            c = conn.cursor()
            if f:
                c.execute("SELECT codigo, descripcion FROM cie10 WHERE codigo LIKE ? OR descripcion LIKE ? LIMIT 200",
                          (f"%{f}%", f"%{f}%"))
            else:
                c.execute("SELECT codigo, descripcion FROM cie10 LIMIT 200")
            filas = c.fetchall()
        finally:
            conn.close()
        for f_ in filas:
            self.tabla.insert("", "end", values=f_)

    def sel(self):
        s = self.tabla.selection()
        if not s: return
        cod, desc = self.tabla.item(s[0])["values"]
        if self.callback:
            self.callback(str(cod), str(desc))
        self.destroy()


# ==================== PRINCIPAL ====================
class AppPrincipal:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Sistema de Expedientes Médicos v{VERSION_ACTUAL}")
        self.root.geometry(tamano_ventana(1100, 700, margen_x=40, margen_y=80))
        self.root.configure(bg=PALETA["fondo"])

        self._header(); self._acciones(); self._tabla(); self._barra_inf()
        self.cargar()

        threading.Thread(target=verificar_actualizacion,
                         args=(self.root,), daemon=True).start()

    def _header(self):
        h = tk.Frame(self.root, bg=PALETA["header"], height=80)
        h.pack(fill="x"); h.pack_propagate(False)
        i = tk.Frame(h, bg=PALETA["header"]); i.pack(side="left", padx=25, pady=15)
        tk.Label(i, text="🏥", bg=PALETA["header"], fg="white",
                 font=(FUENTE, 24)).pack(side="left", padx=(0, 12))
        t = tk.Frame(i, bg=PALETA["header"]); t.pack(side="left")
        tk.Label(t, text="Sistema de Expedientes Médicos",
                 bg=PALETA["header"], fg="white", font=(FUENTE, 16, "bold")).pack(anchor="w")
        tk.Label(t, text=f"v{VERSION_ACTUAL} — Gestión de pacientes y consultas",
                 bg=PALETA["header"], fg="#BFDBFE", font=(FUENTE, 9)).pack(anchor="w")

    def _acciones(self):
        c = tk.Frame(self.root, bg=PALETA["fondo"]); c.pack(fill="x", padx=20, pady=(15, 5))
        crear_boton(c, "➕ Agregar Expediente", self.nuevo, "Exito.TButton").pack(side="left")
        f = tk.Frame(c, bg=PALETA["fondo"]); f.pack(side="right")
        tk.Label(f, text="🔍", bg=PALETA["fondo"], font=(FUENTE, 12)).pack(side="left")
        self.e_buscar = crear_entrada(f, width=30); self.e_buscar.pack(side="left", padx=5)
        self.e_buscar.bind("<KeyRelease>", lambda e: self.cargar())

    def _tabla(self):
        c = tk.Frame(self.root, bg=PALETA["borde"])
        c.pack(fill="both", expand=True, padx=20, pady=10)
        inner = tk.Frame(c, bg="white", padx=2, pady=2)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        cols = ("ID", "Nombre", "Edad", "Sexo", "Última consulta", "Control para")
        self.tabla = ttk.Treeview(inner, columns=cols, show="headings")
        for col in cols:
            self.tabla.heading(col, text=col)
        self.tabla.column("ID", width=60, anchor="center")
        self.tabla.column("Nombre", width=320)
        self.tabla.column("Edad", width=80, anchor="center")
        self.tabla.column("Sexo", width=120, anchor="center")
        self.tabla.column("Última consulta", width=160, anchor="center")
        self.tabla.column("Control para", width=160, anchor="center")
        s = ttk.Scrollbar(inner, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=s.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        s.pack(side="right", fill="y")
        self.tabla.tag_configure("par", background="#F9FAFB")
        self.tabla.tag_configure("impar", background="white")
        self.tabla.bind("<Double-1>", lambda e: self.editar())

    def _barra_inf(self):
        b = tk.Frame(self.root, bg=PALETA["fondo"]); b.pack(fill="x", padx=20, pady=(5, 15))
        crear_boton(b, "✏️ Abrir/Editar", self.editar, "Primario.TButton").pack(side="left", padx=(0, 5))
        crear_boton(b, "🗑 Eliminar", self.eliminar, "Peligro.TButton").pack(side="left", padx=5)
        crear_boton(b, "🔄 Actualizar", self.cargar, "Secundario.TButton").pack(side="left", padx=5)
        crear_boton(b, "💊 Medicamentos", self.abrir_med, "Primario.TButton").pack(side="left", padx=5)
        crear_boton(b, "🔍 CIE-10", self.abrir_cie, "Secundario.TButton").pack(side="left", padx=5)
        crear_boton(b, "⚙️ Opciones", self.abrir_op, "Secundario.TButton").pack(side="left", padx=5)
        crear_boton(b, "📂 Carpeta", self.abrir_carpeta, "Secundario.TButton").pack(side="right")
        self.lbl = tk.Label(b, text="", bg=PALETA["fondo"],
                             fg=PALETA["texto_suave"], font=F_PEQUENA)
        self.lbl.pack(side="right", padx=15)

    def cargar(self):
        for r in self.tabla.get_children():
            self.tabla.delete(r)
        f = self.e_buscar.get().strip().lower()
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("""SELECT id, nombre, edad, sexo, ultima_consulta, control_para
                         FROM expedientes ORDER BY id DESC""")
            filas = c.fetchall()
        finally:
            conn.close()
        i = 0
        for fila in filas:
            if f and f not in (str(fila[1]) or "").lower(): continue
            tag = "par" if i % 2 == 0 else "impar"
            self.tabla.insert("", "end", values=fila, tags=(tag,))
            i += 1
        self.lbl.config(text=f"{i} expediente(s)")

    def nuevo(self):
        FormularioExpediente(self.root, on_save=self.cargar)

    def editar(self):
        s = self.tabla.selection()
        if not s:
            Toast(self.root, "Selecciona un expediente", "aviso"); return
        eid = self.tabla.item(s[0])["values"][0]
        FormularioExpediente(self.root, expediente_id=eid, on_save=self.cargar)

    def eliminar(self):
        s = self.tabla.selection()
        if not s:
            Toast(self.root, "Selecciona un expediente", "aviso"); return
        eid = self.tabla.item(s[0])["values"][0]
        if not messagebox.askyesno("Confirmar", "¿Eliminar expediente y todo su contenido?"):
            return
        conn = conectar_db()
        try:
            c = conn.cursor()
            c.execute("""SELECT ri.codigo, ri.cantidad FROM receta_indicaciones ri
                         JOIN consultas co ON co.id = ri.consulta_id
                         WHERE co.expediente_id=?""", (eid,))
            for cod, cant in c.fetchall():
                c.execute("UPDATE medicamentos SET stock = stock + ? WHERE codigo = ?", (cant, cod))
            c.execute("""DELETE FROM receta_indicaciones WHERE consulta_id IN
                         (SELECT id FROM consultas WHERE expediente_id=?)""", (eid,))
            c.execute("DELETE FROM consultas WHERE expediente_id=?", (eid,))
            c.execute("DELETE FROM adjuntos WHERE expediente_id=?", (eid,))
            c.execute("DELETE FROM expedientes WHERE id=?", (eid,))
            conn.commit()
        finally:
            conn.close()
        carpeta = os.path.join(ADJUNTOS_DIR, f"exp_{eid}")
        if os.path.exists(carpeta):
            shutil.rmtree(carpeta, ignore_errors=True)
        self.cargar()
        Toast(self.root, "Expediente eliminado", "exito")

    def abrir_carpeta(self): abrir_archivo_sistema(APP_DIR)
    def abrir_med(self): VentanaMedicamentos(self.root)
    def abrir_cie(self): VentanaCIE10(self.root)
    def abrir_op(self): VentanaOpciones(self.root)


# ==================== MAIN ====================
if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    configurar_estilos(root)
    app = AppPrincipal(root)
    root.mainloop()