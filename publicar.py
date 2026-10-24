"""Publica tus carpetas de mods para que los launchers de tus amigos se actualicen.

Cada "perfil" es un pack con su propia carpeta de mods en tu PC, por ejemplo:

    MundoRancio  -> Minecraft 1.21.11, neoforge, D:\\RancioLaunchMods
    Randomizer   -> Minecraft 26.3,    neoforge, D:\\RancioLaunchMods_Randomizer

Uso (desde la carpeta RancioLaunch):

    python publicar.py                 -> te muestra un menú para elegir qué perfil subir
    python publicar.py Randomizer      -> sube solo ese perfil (por nombre o por versión)
    python publicar.py todos           -> sube todos los perfiles
    python publicar.py --nuevo         -> agrega un perfil nuevo
    python publicar.py --reconfigurar  -> borra los perfiles y los vuelve a crear

Los perfiles se guardan en publicar_config.json.

Qué hace: copia tus .jar a publicar/<versión>/, regenera manifest.json (con hashes)
y hace git add + commit + push. Requiere que esta carpeta sea un repo de GitHub público.
"""
import json
import os
import re
import shutil
import subprocess
import sys

from generar_manifest import sha256, generar_manifest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "publicar")
CONFIG = os.path.join(AQUI, "publicar_config.json")
LIMITE_GITHUB_MB = 95
LOADERS = {"vanilla", "fabric", "forge", "neoforge", "quilt"}

# Solo se usa para convertir tu config vieja (una sola versión) al formato con perfiles
NOMBRES_CONOCIDOS = {"1.21.11": "MundoRancio", "26.3": "Randomizer"}


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


# ----------------------------------------------------------------------
# CONFIGURACIÓN (perfiles)
# ----------------------------------------------------------------------
def pedir_perfil():
    print("--- Nuevo perfil ---")
    while True:
        version = input("Versión de Minecraft (ej. 1.21.11 o 26.3): ").strip()
        if version:
            break
    nombre = input(f"Nombre que verán en el launcher [{NOMBRES_CONOCIDOS.get(version, version)}]: ").strip()
    nombre = nombre or NOMBRES_CONOCIDOS.get(version, version)
    while True:
        loader = input("Loader (fabric / forge / neoforge / quilt / vanilla) [neoforge]: ").strip().lower() or "neoforge"
        if loader in LOADERS:
            break
        print(f"  '{loader}' no es válido, escribe uno de: {', '.join(sorted(LOADERS))}")
    loader_version = input("Versión exacta del loader (Enter = la última): ").strip().replace(" ", "")
    carpeta = input("Carpeta con los .jar de este perfil (ruta completa): ").strip().strip('"')
    return {
        "nombre": nombre,
        "version": version,
        "loader": loader,
        "loader_version": loader_version,
        "carpeta_mods": carpeta,
    }


def guardar_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def migrar_formato_viejo(cfg):
    """{carpeta_mods, version, loader} -> {perfiles: [ ... ]}"""
    version = cfg.get("version", "")
    perfil = {
        "nombre": NOMBRES_CONOCIDOS.get(version, version),
        "version": version,
        "loader": cfg.get("loader", "neoforge"),
        "loader_version": "",
        "carpeta_mods": cfg.get("carpeta_mods", ""),
    }
    nuevo = {k: v for k, v in cfg.items() if k not in ("carpeta_mods", "version", "loader")}
    nuevo["perfiles"] = [perfil]
    return nuevo


def cargar_config():
    if "--reconfigurar" in sys.argv or not os.path.isfile(CONFIG):
        cfg = {"perfiles": []}
        print("Vamos a registrar tus perfiles de mods.")
        while True:
            cfg["perfiles"].append(pedir_perfil())
            if input("¿Agregar otro perfil? (s/N): ").strip().lower() != "s":
                break
        guardar_config(cfg)
        return cfg

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    if "perfiles" not in cfg:   # config del formato anterior
        cfg = migrar_formato_viejo(cfg)
        guardar_config(cfg)
        print("(Convertí tu publicar_config.json al formato con perfiles.)")

    if "--nuevo" in sys.argv:
        cfg["perfiles"].append(pedir_perfil())
        guardar_config(cfg)

    return cfg


def validar(cfg):
    perfiles = cfg.get("perfiles") or []
    if not perfiles:
        sys.exit("No hay perfiles en publicar_config.json. Usa --reconfigurar.")
    vistas = set()
    for p in perfiles:
        if p.get("loader") not in LOADERS:
            sys.exit(f"Loader inválido en el perfil '{p.get('nombre')}': '{p.get('loader')}'.")
        if not p.get("version"):
            sys.exit(f"El perfil '{p.get('nombre')}' no tiene versión.")
        if p["version"] in vistas:
            sys.exit(f"Dos perfiles usan la versión {p['version']}. Cada perfil necesita una versión distinta.")
        vistas.add(p["version"])


def elegir_perfiles(cfg):
    perfiles = cfg["perfiles"]

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        q = " ".join(args).strip().lower()
        if q in ("todos", "todo", "all"):
            return perfiles
        elegidos = [p for p in perfiles if q in (p["nombre"].lower(), p["version"].lower())]
        if not elegidos:
            disponibles = ", ".join(f"{p['nombre']} ({p['version']})" for p in perfiles)
            sys.exit(f"No existe el perfil '{q}'. Disponibles: {disponibles}")
        return elegidos

    if len(perfiles) == 1:
        return perfiles

    print("¿Qué quieres publicar?")
    for i, p in enumerate(perfiles, 1):
        print(f"  {i}) {p['nombre']}  (Minecraft {p['version']}, {p['loader']})  <-  {p['carpeta_mods']}")
    print(f"  {len(perfiles) + 1}) Todos")
    while True:
        r = input("Elige un número: ").strip()
        if r.isdigit() and 1 <= int(r) <= len(perfiles) + 1:
            n = int(r)
            return perfiles if n == len(perfiles) + 1 else [perfiles[n - 1]]
        print("  Opción inválida.")


# ----------------------------------------------------------------------
# PUBLICACIÓN
# ----------------------------------------------------------------------
def sincronizar(origen, destino):
    """Deja destino con exactamente los .jar de origen."""
    os.makedirs(destino, exist_ok=True)
    jars = {f for f in os.listdir(origen) if f.lower().endswith(".jar")}
    if not jars:
        sys.exit(f"No hay .jar en {origen}")
    for f in os.listdir(destino):
        if f.lower().endswith(".jar") and f not in jars:
            os.remove(os.path.join(destino, f))
            print(f"    - quitado {f}")
    for f in sorted(jars):
        src, dst = os.path.join(origen, f), os.path.join(destino, f)
        mb = os.path.getsize(src) / 1024 / 1024
        if mb > LIMITE_GITHUB_MB:
            sys.exit(f"{f} pesa {mb:.0f} MB y GitHub no deja subir archivos de más de 100 MB")
        if not os.path.isfile(dst) or sha256(src) != sha256(dst):
            shutil.copy2(src, dst)
            print(f"    + copiado {f}")


def escribir_loader_txt(destino, perfil):
    linea = perfil["loader"]
    if perfil.get("loader_version"):
        linea += f" {perfil['loader_version']}"
    with open(os.path.join(destino, "loader.txt"), "w", encoding="utf-8") as f:
        f.write(linea + "\n")
        f.write(f"nombre={perfil['nombre']}\n")


def main():
    cfg = cargar_config()
    validar(cfg)

    base = cfg.get("base_url") or url_base_desde_git()
    if not base:
        sys.exit("No pude deducir la URL de GitHub. Revisa que esta carpeta sea un repo con 'origin' en GitHub.")

    elegidos = elegir_perfiles(cfg)

    print("1) Copiando mods...")
    for p in elegidos:
        origen = p["carpeta_mods"]
        if not os.path.isdir(origen):
            sys.exit(f"No existe la carpeta del perfil '{p['nombre']}': {origen}\n"
                     f"Edita publicar_config.json o usa --reconfigurar.")
        print(f"  [{p['nombre']}]  {origen}  ->  publicar/{p['version']}/")
        destino = os.path.join(RAIZ, p["version"])
        sincronizar(origen, destino)
        escribir_loader_txt(destino, p)

    print("2) Generando manifest.json...")
    generar_manifest(base)

    print("3) Subiendo a GitHub...")
    git("add", "publicar")
    if not git("status", "--porcelain", "publicar").stdout.strip():
        print("No hay cambios nuevos, todo ya estaba publicado.")
    else:
        nombres = ", ".join(p["nombre"] for p in elegidos)
        c = git("commit", "-m", f"Mods actualizados: {nombres}")
        if c.returncode != 0:
            sys.exit(c.stdout + c.stderr)
        p_ = git("push")
        if p_.returncode != 0 and "upstream" in p_.stderr:
            rama = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            p_ = git("push", "-u", "origin", rama)
        if p_.returncode != 0:
            sys.exit("Falló el push:\n" + p_.stdout + p_.stderr)
        print("Subido.")

    print(f"\nMANIFEST_URL = \"{base}/manifest.json\"")
    print("(GitHub puede tardar unos minutos en reflejar los cambios)")


if __name__ == "__main__":
    main()
