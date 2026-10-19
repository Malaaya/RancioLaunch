"""Sincronización de mods contra un manifest.json alojado en internet."""
import hashlib
import os

import requests


class Plan:
    def __init__(self, descargar, borrar):
        self.descargar = descargar      # lista de dicts del manifest (faltan o cambiaron)
        self.borrar = borrar            # rutas de .jar que sobran
        self.total_bytes = sum(m.get("size", 0) for m in descargar)

    @property
    def hay_cambios(self):
        return bool(self.descargar or self.borrar)

    def resumen(self):
        partes = []
        if self.descargar:
            mb = self.total_bytes / 1024 / 1024
            extra = f" (~{mb:.1f} MB)" if self.total_bytes else ""
            partes.append(f"{len(self.descargar)} mod(s) por descargar o actualizar{extra}")
        if self.borrar:
            partes.append(f"{len(self.borrar)} mod(s) viejo(s) por quitar")
        return " y ".join(partes)


def sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 256), b""):
            h.update(bloque)
    return h.hexdigest()


def obtener_manifest(url, timeout=15):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def planificar(mods_manifest, mods_dir):
    """Compara la carpeta local con la lista del manifest."""
    os.makedirs(mods_dir, exist_ok=True)
    esperados = {m["file"]: m for m in mods_manifest}

    descargar = []
    for nombre, mod in esperados.items():
        ruta = os.path.join(mods_dir, nombre)
        if not os.path.isfile(ruta) or sha256_archivo(ruta).lower() != mod["sha256"].lower():
            descargar.append(mod)

    borrar = [
        os.path.join(mods_dir, f)
        for f in os.listdir(mods_dir)
        if f.lower().endswith(".jar") and f not in esperados
    ]
    return Plan(descargar, borrar)


def aplicar(plan, mods_dir, on_status=None, on_progress=None):
    """Borra lo que sobra y descarga lo que falta, verificando el hash."""
    status = on_status or (lambda t: None)
    progreso = on_progress or (lambda v: None)

    for ruta in plan.borrar:
        status(f"Quitando {os.path.basename(ruta)}...")
        os.remove(ruta)

    total = len(plan.descargar)
    for i, mod in enumerate(plan.descargar, start=1):
        nombre = mod["file"]
        destino = os.path.join(mods_dir, nombre)
        parcial = destino + ".part"
        status(f"Mods {i}/{total}: {nombre}")

        h = hashlib.sha256()
        with requests.get(mod["url"], stream=True, timeout=30) as r:
            r.raise_for_status()
            largo = int(r.headers.get("content-length", 0))
            leido = 0
            with open(parcial, "wb") as f:
                for bloque in r.iter_content(chunk_size=1024 * 64):
                    if not bloque:
                        continue
                    f.write(bloque)
                    h.update(bloque)
                    leido += len(bloque)
                    if largo:
                        progreso(((i - 1) + leido / largo) / total)

        if h.hexdigest().lower() != mod["sha256"].lower():
            os.remove(parcial)
            raise RuntimeError(f"El archivo {nombre} llegó corrupto (hash no coincide)")
        os.replace(parcial, destino)
        progreso(i / total)
