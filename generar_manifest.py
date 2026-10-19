"""Genera manifest.json a partir de tus mods.

Estructura esperada (carpeta 'publicar' junto a este script):

    publicar/
      1.20.1/
        loader.txt        <- una línea: fabric | forge | vanilla  (opcional: "fabric 0.15.11")
        sodium.jar
        lithium.jar
      1.16.5/
        loader.txt
        ...

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


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    base = sys.argv[1].rstrip("/")
    manifest = {"versions": {}}

    for version in sorted(os.listdir(RAIZ)):
        carpeta = os.path.join(RAIZ, version)
        if not os.path.isdir(carpeta):
            continue

        loader, loader_version = "vanilla", None
        txt = os.path.join(carpeta, "loader.txt")
        if os.path.isfile(txt):
            partes = open(txt, encoding="utf-8").read().split()
            if partes:
                loader = partes[0].lower()
            if len(partes) > 1:
                loader_version = partes[1]

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

        manifest["versions"][version] = {
            "loader": loader,
            "loader_version": loader_version,
            "mods": mods,
        }
        print(f"{version}: {loader}, {len(mods)} mods")

    salida = os.path.join(RAIZ, "manifest.json")
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Listo: {salida}")


if __name__ == "__main__":
    main()
