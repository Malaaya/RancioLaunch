import os
import re
import json
import hashlib
import sys
import threading
import zipfile
import subprocess
import requests
import traceback
import webbrowser
import ctypes
import tempfile
import xml.etree.ElementTree as ET
from tkinter import messagebox
import tkinter as tk
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageChops, ImageTk

try:
    import customtkinter as ctk
    import minecraft_launcher_lib
except Exception as e:
    print(f"Error al importar librerías: {e}")
    input("Presiona Enter para salir...")
    exit()

import modsync
from auth import MicrosoftAuth, AuthError

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# Función para encontrar archivos incrustados por PyInstaller
def resolver_ruta_recurso(nombre_archivo):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, nombre_archivo)
    return os.path.join(os.path.abspath("."), nombre_archivo)


# ======================================================================
# AJUSTES DE APARIENCIA Y COORDENADAS
# ======================================================================
BLUR = 2             # Desenfoque en 2
GLASS_ALPHA = 12     # Velo blanco del panel (0 = invisible, 255 = blanco)
FIELD_ALPHA = 28     # Blanco en campos y botones translúcidos
BRIGHTNESS = 1.0     # Brillo del fondo desenfocado
BORDER_ALPHA = 130   # Brillo del borde fino del cristal
FIELD_BORDER = 100   # Brillo del borde de campos y botones

W, H = 900, 650
CARD = (250, 55, 650, 595)

# Campos superiores
ENTRY_BOX = (295, 220, 605, 262)
VERSION_BOX = (295, 280, 605, 322)

# Elementos pegados a la parte inferior del recuadro
STATUS_Y = 445
BAR_BOX = (300, 462, 600, 468)
PLAY_BOX = (295, 485, 605, 530)
MS_BOX = (295, 538, 605, 578)

# Control de RAM (debajo del selector de versión)
RAM_LABEL_Y = 341
SLIDER_Y = 375
SLIDER_X0, SLIDER_X1 = 305, 485   # recorrido del centro de la perilla
RAM_BOX = (505, 354, 605, 396)    # recuadro con el valor
RAM_MIN = 1.0                     # GB
RAM_STEP = 0.5                    # GB

# ======================================================================
# VERSIONES / PACKS QUE SE MUESTRAN EN EL SELECTOR
# ----------------------------------------------------------------------
# La "clave" de cada pack es el nombre de su carpeta dentro de publicar/
# y a la vez la versión de Minecraft que se instala (ej. "26.3").
# El nombre que ve el jugador sale de aquí, o del campo "name" del manifest
# (que se define con nombre=... en el loader.txt de esa carpeta).
# ======================================================================
VERSIONS = ["1.21.11", "26.3"]    # respaldo cuando no hay internet
NOMBRES_VERSION = {
    "1.21.11": "MundoRancio",
    "26.3": "Randomizer",
}
VERSION_POR_DEFECTO = "1.21.11"   # la que aparece seleccionada al abrir

GREEN = (0, 168, 89, 240)

# ======================================================================
# CONFIGURACIÓN: mods
# ======================================================================
MANIFEST_URL = "https://raw.githubusercontent.com/Malaaya/RancioLaunch/main/publicar/manifest.json"
EXIGIR_ACTUALIZACION = True

# Repositorio oficial de NeoForge (se usa para instalarlo en Minecraft 26.x)
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"

# Versión de ESTE launcher. Se compara con la publicada en el manifest.
# (publicar_launcher.py la sube solo cuando le pasas un número nuevo)
APP_VERSION = "1.0.1"


class Cancelado(Exception):
    pass


def obtener_ram_total_gb():
    """RAM física total del equipo, en GB enteros (mínimo 1)."""
    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            total = st.ullTotalPhys
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return max(int(total // (1024 ** 3)), 1)
    except Exception:
        return 8


def fmt_gb(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


# ----------------------------------------------------------------------
# UTILIDADES DE DIBUJO (PIL)
# ----------------------------------------------------------------------
def rounded_mask(w, h, radius):
    s = 4
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
    return mask.resize((w, h), Image.LANCZOS)


def draw_rounded(base, box, radius, fill):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    layer = Image.new("RGBA", (w, h), fill)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), rounded_mask(w, h, radius)))
    base.alpha_composite(layer, (x0, y0))


def draw_border(base, box, radius, alpha, width=2):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    outer = rounded_mask(w, h, radius)
    inner_small = rounded_mask(w - 2 * width, h - 2 * width, max(radius - width, 1))
    inner = Image.new("L", (w, h), 0)
    inner.paste(inner_small, (width, width))
    ring = ImageChops.subtract(outer, inner)
    layer = Image.new("RGBA", (w, h), (255, 255, 255, alpha))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), ring))
    base.alpha_composite(layer, (x0, y0))


def construir_fondo():
    ruta_fondo = next(
        (resolver_ruta_recurso(n) for n in ("nahuel.jpg", "teto.jpg") if os.path.exists(resolver_ruta_recurso(n))),
        None
    )
    if ruta_fondo:
        base = Image.open(ruta_fondo).convert("RGBA").resize((W, H))
    else:
        base = Image.new("RGBA", (W, H), (17, 17, 27, 255))

    # Panel de cristal con desenfoque
    cw, ch = CARD[2] - CARD[0], CARD[3] - CARD[1]
    blurred = base.filter(ImageFilter.GaussianBlur(BLUR)) if BLUR > 0 else base.copy()
    blurred = ImageEnhance.Brightness(blurred).enhance(BRIGHTNESS)
    glass = blurred.crop(CARD)
    glass = Image.alpha_composite(glass, Image.new("RGBA", (cw, ch), (255, 255, 255, GLASS_ALPHA)))
    base.paste(glass, (CARD[0], CARD[1]), rounded_mask(cw, ch, 25))
    draw_border(base, CARD, 25, BORDER_ALPHA)

    # Campos y botones translúcidos
    for box in (ENTRY_BOX, VERSION_BOX, MS_BOX, RAM_BOX):
        draw_rounded(base, box, 12, (255, 255, 255, FIELD_ALPHA))
        draw_border(base, box, 12, FIELD_BORDER, width=1)

    draw_rounded(base, PLAY_BOX, 12, GREEN)
    draw_rounded(base, (VERSION_BOX[2] - 44, VERSION_BOX[1] + 5, VERSION_BOX[2] - 6, VERSION_BOX[3] - 5), 10, GREEN)
    draw_rounded(base, BAR_BOX, 3, (255, 255, 255, 150))
    draw_rounded(base, (SLIDER_X0 - 8, SLIDER_Y - 3, SLIDER_X1 + 8, SLIDER_Y + 3), 3, (255, 255, 255, 110))

    # Logo central del panel
    ruta_logo = next(
        (resolver_ruta_recurso(n) for n in ("tetotransparente.png", "teto.jpg", "nahuel.jpg") if os.path.exists(resolver_ruta_recurso(n))),
        None
    )
    if ruta_logo:
        icon = Image.open(ruta_logo).convert("RGBA").resize((75, 75))
        base.paste(icon, (412, 75), icon)

    return base


# ----------------------------------------------------------------------
# APP
# ----------------------------------------------------------------------
class RancioLaunch(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Registrar App ID de Windows para forzar el icono en la barra de tareas
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ranciolabs.ranciolaunch.app.1")
        except Exception:
            pass

        self.title("RancioLaunch")
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)

        # Usar tetotransparente.png para la ventana y la barra de tareas
        ruta_icono = next(
            (resolver_ruta_recurso(n) for n in ("tetotransparente.png", "teto.jpg") if os.path.exists(resolver_ruta_recurso(n))),
            None
        )
        if ruta_icono:
            try:
                img_ico = Image.open(ruta_icono).convert("RGBA")
                self.app_icon = ImageTk.PhotoImage(img_ico)
                self.iconphoto(True, self.app_icon)

                # Generar icono nativo .ico temporal para la barra de Windows
                ruta_ico_temp = os.path.join(os.environ.get("TEMP", "."), "rancio_tetotransparente.ico")
                img_ico.save(ruta_ico_temp, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)])
                self.iconbitmap(ruta_ico_temp)
            except Exception as e:
                print(f"Error asignando icono: {e}")

        self.minecraft_directory = minecraft_launcher_lib.utils.get_minecraft_directory()
        self.progress_max = 0
        self.jugando = False
        self.nombres = dict(NOMBRES_VERSION)   # clave (versión) -> nombre visible
        self.version = VERSION_POR_DEFECTO if VERSION_POR_DEFECTO in VERSIONS else VERSIONS[0]
        self.username = ""   # Campo de texto vacío por defecto
        self.entry_focus = True
        self.cursor_on = True
        self.cuenta = None
        self.logueando = False
        self.codigo_actual = None

        self.ram_max = float(obtener_ram_total_gb())
        cfg = self.cargar_config()
        self.ram_gb = self.ajustar_ram(cfg.get("ram_gb", min(4.0, self.ram_max)))
        self.ram_text = fmt_gb(self.ram_gb)
        self.ram_focus = False
        self.ram_reemplazar = False
        self.ram_dragging = False

        self.auth = MicrosoftAuth(
            os.path.join(self.minecraft_directory, "rancio_auth.json")
        )

        fondo = construir_fondo()
        self.bg_photo = ImageTk.PhotoImage(fondo)

        self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0, bd=0, takefocus=1)
        self.canvas.place(x=0, y=0)
        self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
        self.canvas.focus_set()

        # --- Título principal ---
        self.texto(450, 175, "RancioLaunch", 25, True)

        # --- Entrada de Usuario ---
        ey = (ENTRY_BOX[1] + ENTRY_BOX[3]) // 2
        self.user_t = self.texto(450, ey, self.username, 13, True)
        self.placeholder = self.canvas.create_text(
            450, ey, text="Nombre de Usuario", fill="#e6e6e6",
            font=("Segoe UI", 13, "bold"), state="normal"
        )
        self.cursor = self.canvas.create_line(450, ey - 12, 450, ey + 12, fill="#ffffff", width=2)
        self.actualizar_campo()
        self.parpadear()

        # --- Selector de versión ---
        vy = (VERSION_BOX[1] + VERSION_BOX[3]) // 2
        self.version_t = self.texto((VERSION_BOX[0] + VERSION_BOX[2] - 44) // 2, vy,
                                    self.nombre_version(self.version), 13, True)
        cx = VERSION_BOX[2] - 25
        self.canvas.create_line(cx - 6, vy - 3, cx, vy + 3, cx + 6, vy - 3,
                                fill="#ffffff", width=2, capstyle="round", joinstyle="round")
        self.menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 11))
        for v in VERSIONS:
            self.menu.add_command(label=self.nombre_version(v), command=lambda v=v: self.set_version(v))
        self.after(300, lambda: threading.Thread(target=self.cargar_versiones_publicadas, daemon=True).start())

        # --- Control de RAM ---
        self.canvas.create_text(SLIDER_X0 - 5, RAM_LABEL_Y, text="Memoria RAM", anchor="w",
                                fill="#ffffff", font=("Segoe UI", 10, "bold"))
        self.canvas.create_text(RAM_BOX[2], RAM_LABEL_Y, text=f"Máx. {fmt_gb(self.ram_max)} GB", anchor="e",
                                fill="#cfcfcf", font=("Segoe UI", 9))
        self.ram_fill = self.canvas.create_line(SLIDER_X0, SLIDER_Y, SLIDER_X0, SLIDER_Y,
                                                fill="#00e676", width=6, capstyle="round")
        self.ram_knob = self.canvas.create_oval(0, 0, 0, 0, fill="#ffffff", outline="#00e676", width=2)
        ry = (RAM_BOX[1] + RAM_BOX[3]) // 2
        self.ram_t = self.canvas.create_text(RAM_BOX[0] + 40, ry, text=self.ram_text, fill="#ffffff",
                                             font=("Segoe UI", 13, "bold"))
        self.canvas.create_text(RAM_BOX[2] - 20, ry, text="GB", fill="#cfcfcf", font=("Segoe UI", 10, "bold"))
        self.ram_cursor = self.canvas.create_line(0, ry - 12, 0, ry + 12, fill="#ffffff", width=2, state="hidden")
        self.dibujar_ram()

        # --- Estado y progreso (encima de JUGAR AHORA) ---
        self.status_t = self.texto(450, STATUS_Y, "Listo para jugar", 10, True)
        self.copy_btn = self.canvas.create_text(
            450, STATUS_Y, text="📋", fill="#00e676", font=("Segoe UI", 12, "bold"), state="hidden"
        )
        self.bar_fill = self.canvas.create_line(
            BAR_BOX[0] + 3, (BAR_BOX[1] + BAR_BOX[3]) // 2, BAR_BOX[0] + 3, (BAR_BOX[1] + BAR_BOX[3]) // 2,
            fill="#00e676", width=6, capstyle="round", state="hidden"
        )

        # --- Botones inferiores pegados abajo ---
        self.play_t = self.texto(450, (PLAY_BOX[1] + PLAY_BOX[3]) // 2, "¡JUGAR AHORA!", 14, True)
        self.ms_t = self.texto(450, (MS_BOX[1] + MS_BOX[3]) // 2, "Iniciar sesión con Microsoft", 11, True)

        # --- Eventos de ratón y teclado ---
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Key>", self.on_key)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # Carga rápida directa de sesión guardada
        sesion_local = self.auth.obtener_sesion_guardada()
        if sesion_local:
            self.aplicar_cuenta(sesion_local)
            threading.Thread(target=self.restaurar_sesion, daemon=True).start()

    def texto(self, x, y, txt, size, bold):
        fuente = ("Segoe UI", size, "bold" if bold else "normal")
        return self.canvas.create_text(x, y, text=txt, fill="#ffffff", font=fuente)

    def set_texto(self, item, txt):
        self.canvas.itemconfigure(item, text=txt)

    def actualizar_campo(self):
        ey = (ENTRY_BOX[1] + ENTRY_BOX[3]) // 2
        self.set_texto(self.user_t, self.username)
        vacio = not self.username
        self.canvas.itemconfigure(self.placeholder, state="normal" if vacio else "hidden")
        bbox = self.canvas.bbox(self.user_t) if self.username else None
        cx = (bbox[2] + 2) if bbox else 450
        self.canvas.coords(self.cursor, cx, ey - 12, cx, ey + 12)
        self.mostrar_cursor()

    def mostrar_cursor(self):
        visible = self.entry_focus and self.cursor_on
        self.canvas.itemconfigure(self.cursor, state="normal" if visible else "hidden")
        if "ram_cursor" in self.__dict__:   # todavía no existe durante el arranque
            visible_ram = self.ram_focus and self.cursor_on
            self.canvas.itemconfigure(self.ram_cursor, state="normal" if visible_ram else "hidden")

    def parpadear(self):
        self.cursor_on = not self.cursor_on
        self.mostrar_cursor()
        self.after(500, self.parpadear)

    def on_key(self, e):
        if self.ram_focus:
            if not self.jugando:
                self.on_key_ram(e)
            return
        if not self.entry_focus or self.jugando or self.cuenta:
            return
        if e.keysym == "BackSpace":
            self.username = self.username[:-1]
        elif (e.state & 4) and e.keysym.lower() == "v":
            try:
                pegado = re.sub(r"[^A-Za-z0-9_]", "", self.clipboard_get())
                self.username = (self.username + pegado)[:16]
            except Exception:
                pass
        elif e.char and re.fullmatch(r"[A-Za-z0-9_]", e.char) and len(self.username) < 16:
            self.username += e.char
        else:
            return
        self.cursor_on = True
        self.actualizar_campo()

    @staticmethod
    def dentro(box, x, y):
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def dentro_item(self, item, x, y):
        if self.canvas.itemcget(item, "state") == "hidden":
            return False
        bbox = self.canvas.bbox(item)
        if not bbox:
            return False
        return (bbox[0] - 6) <= x <= (bbox[2] + 6) and (bbox[1] - 6) <= y <= (bbox[3] + 6)

    def on_motion(self, e):
        activo = any(self.dentro(b, e.x, e.y) for b in (VERSION_BOX, PLAY_BOX, MS_BOX))
        activo = activo or self.dentro_item(self.copy_btn, e.x, e.y)
        if self.dentro(ENTRY_BOX, e.x, e.y) or (self.dentro(RAM_BOX, e.x, e.y) and not self.jugando):
            self.canvas.configure(cursor="xterm")
        elif self.en_slider(e.x, e.y) and not self.jugando:
            self.canvas.configure(cursor="hand2")
        else:
            self.canvas.configure(cursor="hand2" if activo else "")

    def on_click(self, e):
        self.canvas.focus_set()

        en_ram = self.dentro(RAM_BOX, e.x, e.y) and not self.jugando
        if self.ram_focus and not en_ram:
            self.confirmar_ram()
        if en_ram and not self.ram_focus:
            self.ram_focus = True
            self.ram_reemplazar = True   # lo primero que se escriba reemplaza el valor

        self.entry_focus = self.dentro(ENTRY_BOX, e.x, e.y)
        self.cursor_on = True
        self.mostrar_cursor()
        self.dibujar_ram()

        if self.dentro_item(self.copy_btn, e.x, e.y):
            self.copiar_codigo()
        elif self.en_slider(e.x, e.y) and not self.jugando:
            self.ram_dragging = True
            self.mover_slider(e.x)
        elif self.dentro(VERSION_BOX, e.x, e.y) and not self.jugando:
            self.menu.tk_popup(self.winfo_rootx() + VERSION_BOX[0], self.winfo_rooty() + VERSION_BOX[3])
        elif self.dentro(PLAY_BOX, e.x, e.y):
            self.iniciar_proceso_juego()
        elif self.dentro(MS_BOX, e.x, e.y) and not self.jugando and not self.logueando:
            self.click_microsoft()

    # ------------------------------------------------------------------
    # RAM
    # ------------------------------------------------------------------
    def ajustar_ram(self, v):
        """Limita al rango permitido y redondea al paso de 0.5 GB."""
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = RAM_MIN
        v = round(v / RAM_STEP) * RAM_STEP
        return max(RAM_MIN, min(v, self.ram_max))

    def ram_a_x(self, gb):
        rango = self.ram_max - RAM_MIN
        frac = (gb - RAM_MIN) / rango if rango > 0 else 0
        return SLIDER_X0 + max(0.0, min(frac, 1.0)) * (SLIDER_X1 - SLIDER_X0)

    def en_slider(self, x, y):
        return (SLIDER_X0 - 14) <= x <= (SLIDER_X1 + 14) and abs(y - SLIDER_Y) <= 14

    def mover_slider(self, x):
        frac = max(0.0, min((x - SLIDER_X0) / (SLIDER_X1 - SLIDER_X0), 1.0))
        self.ram_gb = self.ajustar_ram(RAM_MIN + frac * (self.ram_max - RAM_MIN))
        self.ram_text = fmt_gb(self.ram_gb)
        self.ram_reemplazar = False
        self.dibujar_ram()

    def on_drag(self, e):
        if self.ram_dragging:
            self.mover_slider(e.x)

    def on_release(self, e):
        if self.ram_dragging:
            self.ram_dragging = False
            self.guardar_config()

    def dibujar_ram(self):
        """Redibuja barra, perilla y número según self.ram_gb / self.ram_text."""
        x = self.ram_a_x(self.ram_gb)
        self.canvas.coords(self.ram_fill, SLIDER_X0, SLIDER_Y, x, SLIDER_Y)
        self.canvas.coords(self.ram_knob, x - 8, SLIDER_Y - 8, x + 8, SLIDER_Y + 8)
        self.set_texto(self.ram_t, self.ram_text)
        ry = (RAM_BOX[1] + RAM_BOX[3]) // 2
        bbox = self.canvas.bbox(self.ram_t) if self.ram_text else None
        cx = (bbox[2] + 2) if bbox else RAM_BOX[0] + 40
        self.canvas.coords(self.ram_cursor, cx, ry - 12, cx, ry + 12)
        self.mostrar_cursor()

    def on_key_ram(self, e):
        if e.keysym in ("Return", "KP_Enter", "Escape"):
            self.confirmar_ram()
            return
        if e.keysym == "BackSpace":
            self.ram_text = "" if self.ram_reemplazar else self.ram_text[:-1]
        elif e.char and e.char in "0123456789.,":
            c = e.char.replace(",", ".")
            base = "" if self.ram_reemplazar else self.ram_text
            if c == "." and ("." in base or not base):
                return
            if len(base) >= 5:
                return
            self.ram_text = base + c
        else:
            return
        self.ram_reemplazar = False

        # Actualiza la barra en vivo mientras se escribe
        try:
            v = float(self.ram_text)
        except ValueError:
            v = None
        if v is not None:
            if v > self.ram_max:
                v = self.ram_max
                self.ram_text = fmt_gb(v)
            self.ram_gb = self.ajustar_ram(v)
        self.cursor_on = True
        self.dibujar_ram()

    def confirmar_ram(self):
        """Valida lo escrito a mano, lo ajusta al rango y lo guarda."""
        try:
            v = float(self.ram_text)
        except ValueError:
            v = self.ram_gb
        self.ram_gb = self.ajustar_ram(v)
        self.ram_text = fmt_gb(self.ram_gb)
        self.ram_focus = False
        self.ram_reemplazar = False
        self.dibujar_ram()
        self.guardar_config()

    def ruta_config(self):
        return os.path.join(self.minecraft_directory, "rancio_config.json")

    def cargar_config(self):
        try:
            with open(self.ruta_config(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def guardar_config(self):
        try:
            with open(self.ruta_config(), "w", encoding="utf-8") as f:
                json.dump({"ram_gb": self.ram_gb}, f)
        except Exception:
            pass

    def copiar_codigo(self):
        if not self.codigo_actual:
            return
        self.clipboard_clear()
        self.clipboard_append(self.codigo_actual)
        self.update()
        self.canvas.itemconfigure(self.copy_btn, text="✓", fill="#00e676")
        self.after(1200, lambda: self.canvas.itemconfigure(self.copy_btn, text="📋", fill="#00e676"))

    # ------------------------------------------------------------------
    # SELECTOR DE VERSIÓN / PACKS
    # ------------------------------------------------------------------
    def nombre_version(self, v):
        """Nombre visible de un pack (si no tiene, se muestra la versión tal cual)."""
        return self.nombres.get(v) or v

    def set_version(self, v):
        self.version = v   # la clave interna sigue siendo la versión de Minecraft
        self.set_texto(self.version_t, self.nombre_version(v))

    def cargar_versiones_publicadas(self):
        """Reemplaza la lista fija de versiones por las que hay publicadas en el manifest."""
        try:
            manifest = modsync.obtener_manifest(MANIFEST_URL, timeout=8)
        except Exception:
            return   # sin internet: se queda la lista fija

        publicadas = manifest.get("versions", {})
        for v, info in publicadas.items():
            nombre = (info or {}).get("name")
            if nombre:
                self.nombres[v] = nombre   # el nombre del manifest manda sobre el local

        versiones = list(publicadas.keys())
        if versiones:
            self.mostrar_versiones(versiones)
        self.revisar_actualizacion_launcher(manifest.get("launcher"))

    def mostrar_versiones(self, versiones):
        versiones.sort(key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")], reverse=True)

        def aplicar():
            self.menu.delete(0, "end")
            for v in versiones:
                self.menu.add_command(label=self.nombre_version(v), command=lambda v=v: self.set_version(v))
            self.set_version(VERSION_POR_DEFECTO if VERSION_POR_DEFECTO in versiones else versiones[0])

        self.after(0, aplicar)

    # ------------------------------------------------------------------
    # AUTO-ACTUALIZACIÓN DEL LAUNCHER
    # ------------------------------------------------------------------
    @staticmethod
    def _tupla_version(v):
        return tuple(int(x) if x.isdigit() else 0 for x in str(v).strip().lstrip("vV").split("."))

    def revisar_actualizacion_launcher(self, info):
        """Si el manifest trae un launcher más nuevo, ofrece descargarlo e instalarlo."""
        if not info or not getattr(sys, "frozen", False) or sys.platform != "win32":
            return   # solo tiene sentido en el .exe de Windows
        try:
            if self._tupla_version(info["version"]) <= self._tupla_version(APP_VERSION):
                return
            info["url"]
        except Exception:
            return

        ok = self.preguntar(
            "Actualización del launcher",
            f"Hay una versión nueva de RancioLaunch ({info['version']}).\n"
            f"Tú tienes la {APP_VERSION}.\n\n"
            "¿Actualizar ahora? El launcher se reiniciará solo.",
        )
        if not ok:
            return

        self.set_jugando(True)
        try:
            self.aplicar_actualizacion_launcher(info)
        except Exception as e:
            traceback.print_exc()
            self.actualizar_estado(f"No se pudo actualizar: {str(e)[:20]}")
            self.after(0, lambda: self.dibujar_progreso(0))
            self.set_jugando(False)

    def aplicar_actualizacion_launcher(self, info):
        exe = sys.executable
        nuevo = exe + ".nuevo"

        self.actualizar_estado("Descargando actualización...")
        h = hashlib.sha256()
        with requests.get(info["url"], stream=True, timeout=30) as r:
            r.raise_for_status()
            largo = int(r.headers.get("content-length", 0)) or int(info.get("size", 0))
            leido = 0
            with open(nuevo, "wb") as f:
                for bloque in r.iter_content(chunk_size=1024 * 64):
                    if not bloque:
                        continue
                    f.write(bloque)
                    h.update(bloque)
                    leido += len(bloque)
                    if largo:
                        v = min(leido / largo, 1.0)
                        self.after(0, lambda v=v: self.dibujar_progreso(v))

        esperado = info.get("sha256")
        if esperado and h.hexdigest().lower() != esperado.lower():
            os.remove(nuevo)
            raise RuntimeError("descarga corrupta")

        # Un .exe no se puede reemplazar mientras corre: un script espera a que
        # este proceso termine, cambia el archivo y vuelve a abrir el launcher.
        self.actualizar_estado("Reiniciando...")
        bat = os.path.join(os.environ.get("TEMP", os.path.dirname(exe)), "rancio_actualizar.bat")
        with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(
                "@echo off\n"
                "chcp 65001 >nul\n"
                "set n=0\n"
                ":espera\n"
                "set /a n+=1\n"
                "if %n% GTR 40 goto fin\n"
                "ping -n 2 127.0.0.1 >nul\n"
                f'move /Y "{nuevo}" "{exe}" >nul 2>&1\n'
                "if errorlevel 1 goto espera\n"
                f'start "" "{exe}"\n'
                ":fin\n"
                'del "%~f0"\n'
            )

        # Entorno limpio para que el exe nuevo (PyInstaller onefile) no reutilice
        # la carpeta temporal de este proceso, que va a desaparecer.
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(
            ["cmd", "/c", bat], env=env, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        self.after(0, self.destroy)

    def actualizar_estado(self, texto, codigo=None):
        def _actualizar():
            self.set_texto(self.status_t, texto)
            self.codigo_actual = codigo
            if codigo:
                bbox = self.canvas.bbox(self.status_t)
                if bbox:
                    cx = bbox[2] + 16
                    cy = (bbox[1] + bbox[3]) // 2
                    self.canvas.coords(self.copy_btn, cx, cy)
                    self.canvas.itemconfigure(self.copy_btn, text="📋", fill="#00e676", state="normal")
            else:
                self.canvas.itemconfigure(self.copy_btn, state="hidden")
        self.after(0, _actualizar)

    def set_max(self, max_value):
        self.progress_max = max_value

    def set_progress(self, current):
        if self.progress_max > 0:
            val = min(current / self.progress_max, 1.0)
            self.after(0, lambda: self.dibujar_progreso(val))

    def dibujar_progreso(self, val):
        x0, y0, x1, y1 = BAR_BOX
        y = (y0 + y1) // 2
        if val <= 0:
            self.canvas.itemconfigure(self.bar_fill, state="hidden")
        else:
            largo = (x1 - x0 - 6) * val
            self.canvas.coords(self.bar_fill, x0 + 3, y, x0 + 3 + largo, y)
            self.canvas.itemconfigure(self.bar_fill, state="normal")

    def set_jugando(self, estado):
        self.jugando = estado
        texto = "CARGANDO..." if estado else "¡JUGAR AHORA!"
        self.after(0, lambda: self.set_texto(self.play_t, texto))

    # ------------------------------------------------------------------
    # CUENTA MICROSOFT
    # ------------------------------------------------------------------
    def aplicar_cuenta(self, cuenta):
        self.cuenta = cuenta
        if cuenta:
            self.username = cuenta["name"]
            self.set_texto(self.ms_t, f"Cerrar sesión ({cuenta['name']})")
        else:
            self.username = ""
            self.set_texto(self.ms_t, "Iniciar sesión con Microsoft")
        self.actualizar_campo()

    def restaurar_sesion(self):
        try:
            cuenta = self.auth.refrescar()
            self.after(0, lambda: self.aplicar_cuenta(cuenta))
            self.actualizar_estado(f"Sesión activa: {cuenta['name']}")
        except Exception:
            pass

    def click_microsoft(self):
        if self.cuenta:
            self.auth.cerrar_sesion()
            self.aplicar_cuenta(None)
            return
        self.logueando = True
        threading.Thread(target=self.hacer_login, daemon=True).start()

    def hacer_login(self):
        try:
            def mostrar_codigo(url, codigo):
                self.actualizar_estado(f"Código: {codigo}", codigo=codigo)

            cuenta = self.auth.login_interactivo(callback_codigo=mostrar_codigo)
            self.after(0, lambda: self.aplicar_cuenta(cuenta))
            self.actualizar_estado(f"Sesión iniciada: {cuenta['name']}")
        except AuthError as e:
            self.actualizar_estado(f"Login: {str(e)[:40]}")
        except Exception as e:
            traceback.print_exc()
            self.actualizar_estado(f"Error de login: {str(e)[:25]}")
        finally:
            self.logueando = False

    # ------------------------------------------------------------------
    # INSTALACIÓN Y MODS
    # ------------------------------------------------------------------
    def preguntar(self, titulo, texto):
        resp, listo = {}, threading.Event()

        def _ask():
            resp["v"] = messagebox.askyesno(titulo, texto, parent=self)
            listo.set()

        self.after(0, _ask)
        listo.wait()
        return resp["v"]

    @staticmethod
    def _es_del_loader(vid, loader, mc):
        """Para uso sin internet: ¿este id de versión instalada corresponde a loader + mc?"""
        if loader in ("fabric", "quilt"):
            return vid.startswith(f"{loader}-loader-") and vid.endswith("-" + mc)
        if loader == "forge":
            return vid.startswith(f"{mc}-forge-")
        if loader == "neoforge":
            # Minecraft nuevo (26.x en adelante): NeoForge usa la misma numeración
            # que Minecraft -> 26.3 -> neoforge-26.3.0.36-beta
            mayor = mc.split(".")[0]
            if mayor.isdigit() and int(mayor) >= 26:
                return vid.startswith("neoforge-" + mc + ".")
            # Minecraft clásico: 1.21.11 -> neoforge-21.11.x
            partes = mc.split(".", 1)
            return len(partes) == 2 and vid.startswith("neoforge-" + partes[1] + ".")
        return False

    def instalar_version(self, mc, loader, loader_version, callback):
        """Instala MC (+ fabric/forge/neoforge/quilt si toca) y devuelve el id a lanzar."""
        mld = minecraft_launcher_lib
        carpeta = self.minecraft_directory
        loader = (loader or "vanilla").lower()
        instaladas = lambda: {v["id"] for v in mld.utils.get_installed_versions(carpeta)}

        # Siempre primero el Minecraft vanilla (también deja listo el Java que necesita)
        if mc not in instaladas():
            mld.install.install_minecraft_version(mc, carpeta, callback=callback)
        if loader == "vanilla":
            return mc

        # Minecraft 26.x + NeoForge: la librería aún no lo entiende ("Version 26.3 is not
        # supported"), así que se instala con el instalador oficial de NeoForge.
        if loader == "neoforge" and self._neoforge_nuevo(mc):
            return self.instalar_neoforge_directo(mc, loader_version, callback)

        if not hasattr(mld, "mod_loader"):
            raise RuntimeError("Actualiza la librería: python -m pip install -U minecraft-launcher-lib")
        if loader not in mld.mod_loader.list_mod_loader():
            raise RuntimeError(f"Loader desconocido: '{loader}'")
        ml = mld.mod_loader.get_mod_loader(loader)

        try:
            lv = loader_version or ml.get_latest_loader_version(mc)
        except Exception:
            # sin internet o sin versión: usa uno ya instalado si existe
            for vid in sorted(instaladas(), reverse=True):
                if self._es_del_loader(vid, loader, mc):
                    return vid
            raise

        vid = ml.get_installed_version(mc, lv)
        if vid not in instaladas():
            # El instalador de Forge/NeoForge necesita Java: usa el que trae Minecraft
            java = None
            try:
                info = mld.runtime.get_version_runtime_information(mc, carpeta)
                if info:
                    java = mld.runtime.get_executable_path(info["name"], carpeta)
            except Exception:
                pass
            self.actualizar_estado(f"Instalando {loader}...")
            ml.install(mc, carpeta, loader_version=lv, callback=callback, java=java)
        return vid

    @staticmethod
    def _neoforge_nuevo(mc):
        """True para Minecraft 26.x o más nuevo (numeración nueva de NeoForge)."""
        mayor = mc.split(".")[0]
        return mayor.isdigit() and int(mayor) >= 26

    @staticmethod
    def _ultima_version_neoforge(mc):
        """Última versión de NeoForge publicada para ese Minecraft (ej. 26.3 -> 26.3.0.39-beta)."""
        r = requests.get(NEOFORGE_MAVEN + "/maven-metadata.xml", timeout=15)
        r.raise_for_status()
        todas = [v.text.strip() for v in ET.fromstring(r.content).iter("version") if v.text]
        candidatas = [v for v in todas
                      if v.startswith(mc + ".") and "+" not in v and "snapshot" not in v.lower()]
        if not candidatas:
            raise RuntimeError(f"NeoForge aún no tiene versión para {mc}")
        candidatas.sort(key=lambda v: [int(x) for x in re.findall(r"\d+", v)])
        return candidatas[-1]

    def instalar_neoforge_directo(self, mc, loader_version, callback):
        """Instala NeoForge con su instalador oficial y devuelve el id a lanzar."""
        carpeta = self.minecraft_directory
        instaladas = lambda: {v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(carpeta)}

        lv = loader_version
        if not lv:
            try:
                lv = self._ultima_version_neoforge(mc)
            except Exception:
                # sin internet: usa uno ya instalado si existe
                for vid in sorted(instaladas(), reverse=True):
                    if self._es_del_loader(vid, "neoforge", mc):
                        return vid
                raise

        vid = f"neoforge-{lv}"
        if vid in instaladas():
            return vid

        java = self.asegurar_java(mc, callback) or "java"

        self.actualizar_estado("Descargando NeoForge...")
        url = f"{NEOFORGE_MAVEN}/{lv}/neoforge-{lv}-installer.jar"
        ruta = os.path.join(tempfile.gettempdir(), f"neoforge-{lv}-installer.jar")
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            largo = int(r.headers.get("content-length", 0))
            leido = 0
            with open(ruta, "wb") as f:
                for bloque in r.iter_content(chunk_size=1024 * 64):
                    if not bloque:
                        continue
                    f.write(bloque)
                    leido += len(bloque)
                    if largo:
                        v = min(leido / largo, 1.0)
                        self.after(0, lambda v=v: self.dibujar_progreso(v))

        # El instalador pide que exista launcher_profiles.json
        perfiles = os.path.join(carpeta, "launcher_profiles.json")
        if not os.path.exists(perfiles):
            with open(perfiles, "w", encoding="utf-8") as f:
                json.dump({"profiles": {}, "version": 3}, f)

        self.actualizar_estado("Instalando NeoForge...")
        extra = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([java, "-jar", ruta, "--installClient", carpeta],
                           capture_output=True, text=True, **extra)
        try:
            os.remove(ruta)
        except OSError:
            pass
        if r.returncode != 0:
            print((r.stdout or "") + (r.stderr or ""))
            raise RuntimeError("Falló el instalador de NeoForge")
        if vid not in instaladas():
            raise RuntimeError(f"NeoForge no quedó instalado ({vid})")
        return vid

    def asegurar_java(self, mc, callback):
        """Devuelve la ruta del Java que usa Minecraft, instalándolo si falta.
        Así el launcher no depende de que el usuario tenga Java en el PATH."""
        mld = minecraft_launcher_lib
        carpeta = self.minecraft_directory
        try:
            info = mld.runtime.get_version_runtime_information(mc, carpeta)
            if not info:
                return None
            nombre = info["name"]
            ruta = mld.runtime.get_executable_path(nombre, carpeta)
            if not ruta or not os.path.exists(ruta):
                self.actualizar_estado("Instalando Java...")
                mld.runtime.install_jvm_runtime(nombre, carpeta, callback=callback)
                ruta = mld.runtime.get_executable_path(nombre, carpeta)
            return ruta if ruta and os.path.exists(ruta) else None
        except Exception as e:
            print(f"No se pudo preparar Java: {e}")
            return None

    def sincronizar_mods(self, entrada, mods_dir):
        plan = modsync.planificar(entrada.get("mods", []), mods_dir)
        if not plan.hay_cambios:
            return
        ok = self.preguntar(
            "Actualización de mods",
            f"Hay cambios en los mods:\n\n{plan.resumen()}\n\n¿Actualizar ahora?",
        )
        if not ok:
            if EXIGIR_ACTUALIZACION:
                raise Cancelado()
            return
        modsync.aplicar(
            plan, mods_dir, self.actualizar_estado,
            lambda v: self.after(0, lambda: self.dibujar_progreso(v)),
        )
        self.actualizar_estado("¡Mods sincronizados!")

    def iniciar_proceso_juego(self):
        if self.jugando:
            return
        if self.ram_focus:
            self.confirmar_ram()
        self.set_jugando(True)
        threading.Thread(target=self.ejecutar_minecraft, daemon=True).start()

    def ejecutar_minecraft(self):
        try:
            mc = self.version
            # Cada pack tiene su propia carpeta de juego (y por lo tanto sus propios mods):
            #   .minecraft/rancio/1.21.11/mods  -> MundoRancio
            #   .minecraft/rancio/26.3/mods     -> Randomizer
            game_dir = os.path.join(self.minecraft_directory, "rancio", mc)
            mods_dir = os.path.join(game_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)

            # 1. Cuenta
            if self.cuenta:
                self.actualizar_estado("Verificando sesión...")
                self.cuenta = self.auth.refrescar()
                options = {
                    "username": self.cuenta["name"],
                    "uuid": self.cuenta["id"],
                    "token": self.cuenta["access_token"],
                }
            else:
                options = {"username": self.username.strip() or "RancioJugador", "uuid": "", "token": ""}
            options["gameDirectory"] = game_dir

            ram_mb = int(self.ram_gb * 1024)
            options["jvmArguments"] = [f"-Xmx{ram_mb}M", f"-Xms{min(ram_mb, 1024)}M"]

            # 2. Manifest de mods
            entrada = None
            try:
                self.actualizar_estado("Buscando actualizaciones...")
                entrada = modsync.obtener_manifest(MANIFEST_URL).get("versions", {}).get(mc)
            except Exception as e:
                print(f"Manifest no disponible: {e}")
                self.actualizar_estado("Sin conexión al servidor de mods")

            # 3. Minecraft + loader
            callback = {
                "setStatus": self.actualizar_estado,
                "setProgress": self.set_progress,
                "setMax": self.set_max,
            }
            self.actualizar_estado(f"Instalando {mc}...")
            loader = (entrada or {}).get("loader", "vanilla")
            version_id = self.instalar_version(mc, loader, (entrada or {}).get("loader_version"), callback)

            # Java propio de Minecraft (no depende del Java del sistema)
            java_path = self.asegurar_java(mc, callback)
            if java_path:
                options["executablePath"] = java_path

            # 4. Mods
            if entrada:
                self.sincronizar_mods(entrada, mods_dir)

            # 5. Lanzar
            self.actualizar_estado("Lanzando Minecraft...")
            comando = minecraft_launcher_lib.command.get_minecraft_command(
                version_id, self.minecraft_directory, options
            )

            self.after(0, self.iconify)
            extra = {}
            if sys.platform == "win32":
                extra["creationflags"] = subprocess.CREATE_NO_WINDOW   # sin ventana de consola
            subprocess.call(
                comando, cwd=game_dir,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **extra
            )
            self.after(0, self.deiconify)

            self.actualizar_estado("Listo para jugar")

        except Cancelado:
            self.actualizar_estado("Actualización cancelada")
        except AuthError as e:
            self.after(0, lambda: self.aplicar_cuenta(None))
            self.actualizar_estado(f"Inicia sesión de nuevo: {str(e)[:25]}")
        except Exception as e:
            traceback.print_exc()
            self.actualizar_estado(f"Error: {str(e)[:30]}")
        finally:
            self.after(0, lambda: self.dibujar_progreso(0))
            self.set_jugando(False)


if __name__ == "__main__":
    try:
        app = RancioLaunch()
        app.mainloop()
    except Exception as e:
        print("\n--- ¡Ocurrió un error al iniciar el Launcher! ---")
        traceback.print_exc()
        input("\nPresiona Enter para cerrar la consola...")  # nahuel
