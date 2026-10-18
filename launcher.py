import os
import re
import sys
import threading
import zipfile
import subprocess
import requests
import traceback
import tkinter as tk
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageChops, ImageTk

try:
    import customtkinter as ctk
    import minecraft_launcher_lib
except Exception as e:
    print(f"Error al importar librerías: {e}")
    input("Presiona Enter para salir...")
    exit()

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Función para encontrar archivos incrustados por PyInstaller
def resolver_ruta_recurso(nombre_archivo):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, nombre_archivo)
    return os.path.join(os.path.abspath("."), nombre_archivo)

# ======================================================================
# AJUSTES DE APARIENCIA
# ======================================================================
BLUR = 1           # desenfoque del panel (0 = nítido, 25 = muy borroso)
GLASS_ALPHA = 12    # velo blanco del panel (0 = invisible, 255 = blanco)
FIELD_ALPHA = 28    # blanco en campos y botón salir
BRIGHTNESS = 1.0    # brillo del fondo desenfocado
BORDER_ALPHA = 130  # brillo del borde fino del cristal
FIELD_BORDER = 100  # brillo del borde de campos y botones

W, H = 900, 650
CARD = (250, 55, 650, 595)
ENTRY_BOX = (295, 235, 605, 277)
VERSION_BOX = (295, 291, 605, 333)
PLAY_BOX = (295, 353, 605, 398)
EXIT_BOX = (295, 410, 605, 450)
BAR_BOX = (300, 494, 600, 500)
VERSIONS = ["1.20.1", "1.19.4", "1.16.5"]
GREEN = (0, 168, 89, 240)


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
    ruta_nahuel = resolver_ruta_recurso("nahuel.jpg")
    ruta_teto = resolver_ruta_recurso("teto.jpg")

    bg_path = next((p for p in (ruta_nahuel, ruta_teto) if os.path.exists(p)), None)
    if bg_path:
        base = Image.open(bg_path).convert("RGBA").resize((W, H))
    else:
        base = Image.new("RGBA", (W, H), (17, 17, 27, 255))

    # Panel de cristal
    cw, ch = CARD[2] - CARD[0], CARD[3] - CARD[1]
    blurred = base.filter(ImageFilter.GaussianBlur(BLUR)) if BLUR > 0 else base.copy()
    blurred = ImageEnhance.Brightness(blurred).enhance(BRIGHTNESS)
    glass = blurred.crop(CARD)
    glass = Image.alpha_composite(glass, Image.new("RGBA", (cw, ch), (255, 255, 255, GLASS_ALPHA)))
    base.paste(glass, (CARD[0], CARD[1]), rounded_mask(cw, ch, 25))
    draw_border(base, CARD, 25, BORDER_ALPHA)

    # Campos y botones translúcidos
    for box in (ENTRY_BOX, VERSION_BOX, EXIT_BOX):
        draw_rounded(base, box, 12, (255, 255, 255, FIELD_ALPHA))
        draw_border(base, box, 12, FIELD_BORDER, width=1)

    draw_rounded(base, PLAY_BOX, 12, GREEN)
    draw_rounded(base, (VERSION_BOX[2] - 44, VERSION_BOX[1] + 5, VERSION_BOX[2] - 6, VERSION_BOX[3] - 5), 10, GREEN)
    draw_rounded(base, BAR_BOX, 3, (255, 255, 255, 150))

    # Logo central (Teto)
    icon_path = next((p for p in (ruta_teto, ruta_nahuel) if os.path.exists(p)), None)
    if icon_path:
        icon = Image.open(icon_path).convert("RGBA").resize((75, 75))
        base.paste(icon, (412, 80), rounded_mask(75, 75, 10))

    return base


# ----------------------------------------------------------------------
# APP
# ----------------------------------------------------------------------
class RancioLaunch(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("RancioLaunch")
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)

        self.minecraft_directory = minecraft_launcher_lib.utils.get_minecraft_directory()
        self.progress_max = 0
        self.jugando = False
        self.version = VERSIONS[0]
        self.username = "RancioJugador"
        self.entry_focus = True
        self.cursor_on = True

        fondo = construir_fondo()
        self.bg_photo = ImageTk.PhotoImage(fondo)

        self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0, bd=0, takefocus=1)
        self.canvas.place(x=0, y=0)
        self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
        self.canvas.focus_set()

        # --- Textos ---
        self.texto(450, 178, "RancioLaunch", 25, True)
        self.texto(450, 210, "Ingresa tu Nick para iniciar el viaje", 11, False)

        ey = (ENTRY_BOX[1] + ENTRY_BOX[3]) // 2
        self.user_t = self.texto(450, ey, self.username, 13, True)
        self.placeholder = self.canvas.create_text(
            450, ey, text="Nombre de Usuario", fill="#e6e6e6",
            font=("Segoe UI", 13, "bold"), state="hidden"
        )
        self.cursor = self.canvas.create_line(450, ey - 12, 450, ey + 12, fill="#ffffff", width=2)
        self.actualizar_campo()
        self.parpadear()

        # --- Selector de versión ---
        vy = (VERSION_BOX[1] + VERSION_BOX[3]) // 2
        self.version_t = self.texto((VERSION_BOX[0] + VERSION_BOX[2] - 44) // 2, vy, self.version, 13, True)
        cx = VERSION_BOX[2] - 25
        self.canvas.create_line(cx - 6, vy - 3, cx, vy + 3, cx + 6, vy - 3,
                                fill="#ffffff", width=2, capstyle="round", joinstyle="round")
        self.menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 11))
        for v in VERSIONS:
            self.menu.add_command(label=v, command=lambda v=v: self.set_version(v))

        # --- Botones ---
        self.play_t = self.texto(450, (PLAY_BOX[1] + PLAY_BOX[3]) // 2, "¡JUGAR AHORA!", 14, True)
        self.texto(450, (EXIT_BOX[1] + EXIT_BOX[3]) // 2, "Salir del launcher", 12, True)

        # --- Estado y progreso ---
        self.status_t = self.texto(450, 473, "Listo para jugar", 10, True)
        self.bar_fill = self.canvas.create_line(
            BAR_BOX[0] + 3, (BAR_BOX[1] + BAR_BOX[3]) // 2, BAR_BOX[0] + 3, (BAR_BOX[1] + BAR_BOX[3]) // 2,
            fill="#00e676", width=6, capstyle="round", state="hidden"
        )

        # --- Eventos ---
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Key>", self.on_key)

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

    def parpadear(self):
        self.cursor_on = not self.cursor_on
        self.mostrar_cursor()
        self.after(500, self.parpadear)

    def on_key(self, e):
        if not self.entry_focus or self.jugando:
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

    def on_motion(self, e):
        activo = any(self.dentro(b, e.x, e.y) for b in (VERSION_BOX, PLAY_BOX, EXIT_BOX))
        if self.dentro(ENTRY_BOX, e.x, e.y):
            self.canvas.configure(cursor="xterm")
        else:
            self.canvas.configure(cursor="hand2" if activo else "")

    def on_click(self, e):
        self.canvas.focus_set()
        self.entry_focus = self.dentro(ENTRY_BOX, e.x, e.y)
        self.mostrar_cursor()

        if self.dentro(VERSION_BOX, e.x, e.y) and not self.jugando:
            self.menu.tk_popup(self.winfo_rootx() + VERSION_BOX[0], self.winfo_rooty() + VERSION_BOX[3])
        elif self.dentro(PLAY_BOX, e.x, e.y):
            self.iniciar_proceso_juego()
        elif self.dentro(EXIT_BOX, e.x, e.y):
            self.destroy()

    def set_version(self, v):
        self.version = v
        self.set_texto(self.version_t, v)

    def actualizar_estado(self, texto):
        self.after(0, lambda: self.set_texto(self.status_t, texto))

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

    def descargar_mods_automaticos(self):
        mods_dir = os.path.join(self.minecraft_directory, "mods")
        os.makedirs(mods_dir, exist_ok=True)
        url_zip_mods = "https://tu-servidor-o-enlace.com/tus-mods.zip"

        try:
            self.actualizar_estado("Descargando mods...")
            zip_path = os.path.join(self.minecraft_directory, "temp_mods.zip")
            response = requests.get(url_zip_mods, stream=True, timeout=15)
            if response.status_code == 200:
                with open(zip_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(mods_dir)
                os.remove(zip_path)
                self.actualizar_estado("¡Mods sincronizados!")
        except Exception as e:
            print(f"Aviso de mods: {e}")

    def iniciar_proceso_juego(self):
        if self.jugando:
            return
        self.set_jugando(True)
        threading.Thread(target=self.ejecutar_minecraft, daemon=True).start()

    def ejecutar_minecraft(self):
        try:
            version_id = self.version
            username = self.username.strip() or "RancioJugador"

            options = {
                "username": username,
                "uuid": "",
                "token": ""
            }

            self.actualizar_estado(f"Instalando {version_id}...")

            callback = {
                "setStatus": self.actualizar_estado,
                "setProgress": self.set_progress,
                "setMax": self.set_max,
            }

            minecraft_launcher_lib.install.install_minecraft_version(
                version_id, self.minecraft_directory, callback=callback
            )
            self.descargar_mods_automaticos()

            self.actualizar_estado("Lanzando Minecraft...")
            minecraft_command = minecraft_launcher_lib.command.get_minecraft_command(
                version_id, self.minecraft_directory, options
            )

            self.after(0, self.iconify)
            subprocess.call(minecraft_command)
            self.after(0, self.deiconify)

            self.actualizar_estado("Listo para jugar")
            self.after(0, lambda: self.dibujar_progreso(0))
            self.set_jugando(False)

        except Exception as e:
            traceback.print_exc()
            self.actualizar_estado(f"Error: {str(e)[:30]}")
            self.set_jugando(False)


if __name__ == "__main__":
    try:
        app = RancioLaunch()
        app.mainloop()
    except Exception as e:
        print("\n--- Error al iniciar el Launcher ---")
        traceback.print_exc()
        input("\nPresiona Enter para cerrar la consola...")