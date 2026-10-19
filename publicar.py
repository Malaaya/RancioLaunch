"""Publica tu carpeta de mods para que los launchers de tus amigos se actualicen.

Uso (desde la carpeta RancioLaunch):
    python publicar.py

La primera vez te pregunta la carpeta de mods, la versión de Minecraft y el loader,
y lo guarda en publicar_config.json. Las siguientes veces solo corre y listo.
Loaders válidos: fabric, forge, neoforge, quilt, vanilla.
Para cambiar algo: python publicar.py --reconfigurar

Qué hace: copia tus .jar a publicar/<versión>/, regenera manifest.json (con hashes)
y hace git add + commit + push. Requiere que esta carpeta sea un repo de GitHub público.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote

from generar_manifest import sha256

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "publicar")
CONFIG = os.path.join(AQUI, "publicar_config.json")
LIMITE_GITHUB_MB = 95
LOADERS = {"vanilla", "fabric", "forge", "neoforge", "quilt"}


def git(*args):
    return subprocess.run(["git", *args], cwd=AQUI, capture_output=True, text=True)


def url_base_desde_git():
    """Deduce https://raw.githubusercontent.com/USUARIO/REPO/RAMA/publicar desde el remote."""
    r = git("remote", "get-url", "origin")
    if r.returncode != 0:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?\s*$", r.stdout.strip())
    if not m:
        return None
    rama = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{rama}/publicar"


def configurar():
    print("--- Configuración (se guarda en publicar_config.json) ---")
    carpeta = input("Carpeta con tus mods (ruta completa): ").strip().strip('"')
    version = input("Versión de Minecraft (ej. 1.20.1): ").strip()
    while True:
        loader = input("Loader (fabric / forge / neoforge / quilt / vanilla): ").strip().lower() or "fabric"
        if loader in LOADERS:
            break
        print(f"  '{loader}' no es válido, escribe uno de: {', '.join(sorted(LOADERS))}")
    cfg = {"carpeta_mods": carpeta, "version": version, "loader": loader}
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def cargar_config():
    if "--reconfigurar" in sys.argv or not os.path.isfile(CONFIG):
        return configurar()
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def sincronizar(origen, destino):
    """Deja destino con exactamente los .jar de origen."""
    os.makedirs(destino, exist_ok=True)
    jars = {f for f in os.listdir(origen) if f.lower().endswith(".jar")}
    if not jars:
        sys.exit(f"No hay .jar en {origen}")
    for f in os.listdir(destino):
        if f.lower().endswith(".jar") and f not in jars:
            os.remove(os.path.join(destino, f))
            print(f"  - quitado {f}")
    for f in sorted(jars):
        src, dst = os.path.join(origen, f), os.path.join(destino, f)
        mb = os.path.getsize(src) / 1024 / 1024
        if mb > LIMITE_GITHUB_MB:
            sys.exit(f"{f} pesa {mb:.0f} MB y GitHub no deja subir archivos de más de 100 MB")
        if not os.path.isfile(dst) or sha256(src) != sha256(dst):
            shutil.copy2(src, dst)
            print(f"  + copiado {f}")


def generar_manifest(base):
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
        mods = [{
            "file": f,
            "url": f"{base}/{quote(version)}/{quote(f)}",
            "sha256": sha256(os.path.join(carpeta, f)),
            "size": os.path.getsize(os.path.join(carpeta, f)),
        } for f in sorted(os.listdir(carpeta)) if f.lower().endswith(".jar")]
        manifest["versions"][version] = {"loader": loader, "loader_version": loader_version, "mods": mods}
        print(f"  {version}: {loader}, {len(mods)} mods")
    with open(os.path.join(RAIZ, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def main():
    cfg = cargar_config()
    origen = cfg["carpeta_mods"]
    if cfg.get("loader") not in LOADERS:
        sys.exit(f"Loader inválido en publicar_config.json: '{cfg.get('loader')}'. Usa --reconfigurar.")
    if not os.path.isdir(origen):
        sys.exit(f"No existe la carpeta: {origen}  (usa --reconfigurar)")

    base = cfg.get("base_url") or url_base_desde_git()
    if not base:
        sys.exit("No pude deducir la URL de GitHub. Revisa que esta carpeta sea un repo con 'origin' en GitHub.")

    print("1) Copiando mods...")
    dest = os.path.join(RAIZ, cfg["version"])
    sincronizar(origen, dest)
    with open(os.path.join(dest, "loader.txt"), "w", encoding="utf-8") as f:
        f.write(cfg["loader"] + "\n")

    print("2) Generando manifest.json...")
    generar_manifest(base)

    print("3) Subiendo a GitHub...")
    git("add", "publicar")
    if not git("status", "--porcelain", "publicar").stdout.strip():
        print("No hay cambios nuevos, todo ya estaba publicado.")
    else:
        c = git("commit", "-m", f"Mods {cfg['version']} actualizados")
        if c.returncode != 0:
            sys.exit(c.stdout + c.stderr)
        p = git("push")
        if p.returncode != 0 and "upstream" in p.stderr:
            rama = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            p = git("push", "-u", "origin", rama)
        if p.returncode != 0:
            sys.exit("Falló el push:\n" + p.stdout + p.stderr)
        print("Subido.")

    print(f"\nMANIFEST_URL = \"{base}/manifest.json\"")
    print("(si es la primera vez, pégala en launcher.py y recompila; GitHub puede tardar unos minutos en reflejar cambios)")


if __name__ == "__main__":
    main()
