"""Genera manifest.json a partir de tus mods.

Estructura esperada (carpeta 'publicar' junto a este script):

    publicar/
        1.21.11/                <- nombre de la carpeta = versión de Minecraft
            loader.txt          <- ver formato abajo
            sodium.jar
            lithium.jar
        26.3/
            loader.txt
            ...

Formato de loader.txt (una cosa por línea, todo opcional salvo la primera):

    neoforge                    <- loader: fabric | forge | neoforge | quilt | vanilla
    nombre=Randomizer           <- nombre que se ve en el selector del launcher

    (si quieres fijar la versión exacta del loader: "neoforge 26.3.0.39-beta")

Uso:
    python generar_manifest.py https://raw.githubusercontent.com/USUARIO/REPO/main/publicar

Sube la carpeta 'publicar' completa (manifest.json incluido) a ese lugar.
"""
import hashlib
import json
import os
import sys
from urllib.parse import quote

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publicar")


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1024 * 256), b""):
            h.update(b)
    return h.hexdigest()


def leer_loader_txt(ruta):
    """Devuelve (loader, loader_version, nombre) leyendo loader.txt."""
    loader, loader_version, nombre = "vanilla", None, None
    if not os.path.isfile(ruta):
        return loader, loader_version, nombre
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            if "=" in linea:
                clave, valor = linea.split("=", 1)
                if clave.strip().lower() in ("nombre", "name"):
                    nombre = valor.strip() or None
                continue
            partes = linea.split()
            loader = partes[0].lower()
            if len(partes) > 1:
                loader_version = partes[1]
    return loader, loader_version, nombre


def generar_manifest(base):
    """Recorre publicar/<versión>/ y escribe publicar/manifest.json."""
    manifest = {"versions": {}}

    previo = os.path.join(RAIZ, "manifest.json")
    if os.path.isfile(previo):   # conserva los datos del launcher publicados antes
        try:
            with open(previo, encoding="utf-8") as f:
                datos_launcher = json.load(f).get("launcher")
            if datos_launcher:
                manifest["launcher"] = datos_launcher
        except Exception:
            pass

    for version in sorted(os.listdir(RAIZ)):
        carpeta = os.path.join(RAIZ, version)
        if not os.path.isdir(carpeta):
            continue

        loader, loader_version, nombre = leer_loader_txt(os.path.join(carpeta, "loader.txt"))

        mods = []
        for f in sorted(os.listdir(carpeta)):
            if not f.lower().endswith(".jar"):
                continue
            ruta = os.path.join(carpeta, f)
            mods.append({
                "file": f,
                "url": f"{base}/{quote(version)}/{quote(f)}",
                "sha256": sha256(ruta),
                "size": os.path.getsize(ruta),
            })

        entrada = {}
        if nombre:
            entrada["name"] = nombre
        entrada["loader"] = loader
        entrada["loader_version"] = loader_version
        entrada["mods"] = mods
        manifest["versions"][version] = entrada
        print(f"{version} ({nombre or 'sin nombre'}): {loader}, {len(mods)} mods")

    salida = os.path.join(RAIZ, "manifest.json")
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Listo: {salida}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    generar_manifest(sys.argv[1].rstrip("/"))


if __name__ == "__main__":
    main()
