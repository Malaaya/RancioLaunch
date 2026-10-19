import os
import re
import sys
import threading
import zipfile
import subprocess
import requests
import traceback
import webbrowser
import ctypes
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
BLUR = 2           # Desenfoque en 2
GLASS_ALPHA = 12    # Velo blanco del panel (0 = invisible, 255 = blanco)
FIELD_ALPHA = 28    # Blanco en campos y botones translúcidos
BRIGHTNESS = 1.0    # Brillo del fondo desenfocado
BORDER_ALPHA = 130  # Brillo del borde fino del cristal
FIELD_BORDER = 100  # Brillo del borde de campos y botones

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

VERSIONS = ["1.20.1", "1.19.4", "1.16.5"]
GREEN = (0, 168, 89, 240)

# ======================================================================
# CONFIGURACIÓN: mods
# ======================================================================
MANIFEST_URL = "https://raw.githubusercontent.com/TU-USUARIO/TU-REPO/main/publicar/manifest.json"
EXIGIR_ACTUALIZACION = True


class Cancelado(Exception):
    pass


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
    for box in (ENTRY_BOX, VERSION_BOX, MS_BOX):
        draw_rounded(base, box, 12, (255, 255, 255, FIELD_ALPHA))
        draw_border(base, box, 12, FIELD_BORDER, width=1)

    draw_rounded(base, PLAY_BOX, 12, GREEN)
    draw_rounded(base, (VERSION_BOX[2] - 44, VERSION_BOX[1] + 5, VERSION_BOX[2] - 6, VERSION_BOX[3] - 5), 10, GREEN)
    draw_rounded(base, BAR_BOX, 3, (255, 255, 255, 150))

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
        self.version = VERSIONS[0]
        self.username = ""  # Campo de texto vacío por defecto
        self.entry_focus = True
        self.cursor_on = True
        self.cuenta = None
        self.logueando = False
        self.codigo_actual = None
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
        self.version_t = self.texto((VERSION_BOX[0] + VERSION_BOX[2] - 44) // 2, vy, self.version, 13, True)
        cx = VERSION_BOX[2] - 25
        self.canvas.create_line(cx - 6, vy - 3, cx, vy + 3, cx + 6, vy - 3,
                                fill="#ffffff", width=2, capstyle="round", joinstyle="round")
        self.menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 11))
        for v in VERSIONS:
            self.menu.add_command(label=v, command=lambda v=v: self.set_version(v))

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

    def parpadear(self):
        self.cursor_on = not self.cursor_on
        self.mostrar_cursor()
        self.after(500, self.parpadear)

    def on_key(self, e):
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
        if self.dentro(ENTRY_BOX, e.x, e.y):
            self.canvas.configure(cursor="xterm")
        else:
            self.canvas.configure(cursor="hand2" if activo else "")

    def on_click(self, e):
        self.canvas.focus_set()
        self.entry_focus = self.dentro(ENTRY_BOX, e.x, e.y)
        self.mostrar_cursor()

        if self.dentro_item(self.copy_btn, e.x, e.y):
            self.copiar_codigo()
        elif self.dentro(VERSION_BOX, e.x, e.y) and not self.jugando:
            self.menu.tk_popup(self.winfo_rootx() + VERSION_BOX[0], self.winfo_rooty() + VERSION_BOX[3])
        elif self.dentro(PLAY_BOX, e.x, e.y):
            self.iniciar_proceso_juego()
        elif self.dentro(MS_BOX, e.x, e.y) and not self.jugando and not self.logueando:
            self.click_microsoft()

    def copiar_codigo(self):
        if not self.codigo_actual:
            return
        self.clipboard_clear()
        self.clipboard_append(self.codigo_actual)
        self.update()
        self.canvas.itemconfigure(self.copy_btn, text="✓", fill="#00e676")
        self.after(1200, lambda: self.canvas.itemconfigure(self.copy_btn, text="📋", fill="#00e676"))

    def set_version(self, v):
        self.version = v
        self.set_texto(self.version_t, v)

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

    def instalar_version(self, mc, loader, loader_version, callback):
        mld = minecraft_launcher_lib
        carpeta = self.minecraft_directory
        instaladas = lambda: {v["id"] for v in mld.utils.get_installed_versions(carpeta)}

        if loader == "fabric":
            try:
                lv = loader_version or mld.fabric.get_latest_loader_version()
            except Exception:
                for vid in instaladas():
                    if vid.startswith("fabric-loader-") and vid.endswith("-" + mc):
                        return vid
                raise
            vid = f"fabric-loader-{lv}-{mc}"
            if vid not in instaladas():
                mld.fabric.install_fabric(mc, carpeta, loader_version=lv, callback=callback)
            return vid

        if loader == "forge":
            fv = loader_version or mld.forge.find_forge_version(mc)
            if not fv:
                raise RuntimeError(f"No hay Forge para {mc}")
            vid = mld.forge.forge_to_installed_version(fv)
            if vid not in instaladas():
                mld.forge.install_forge_version(fv, carpeta, callback=callback)
            return vid

        if mc not in instaladas():
            mld.install.install_minecraft_version(mc, carpeta, callback=callback)
        return mc

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
        self.set_jugando(True)
        threading.Thread(target=self.ejecutar_minecraft, daemon=True).start()

    def ejecutar_minecraft(self):
        try:
            mc = self.version
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

            # 4. Mods
            if entrada:
                self.sincronizar_mods(entrada, mods_dir)

            # 5. Lanzar
            self.actualizar_estado("Lanzando Minecraft...")
            comando = minecraft_launcher_lib.command.get_minecraft_command(
                version_id, self.minecraft_directory, options
            )
            self.after(0, self.iconify)
            subprocess.call(comando, cwd=game_dir)
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
        print("\n--- Error al iniciar el Launcher ---")
        traceback.print_exc()
        input("\nPresiona Enter para cerrar la consola...") #nahuel 