"""Compila el launcher y lo publica para que los demás se actualicen solos.

Uso (desde la carpeta RancioLaunch):
    python publicar_launcher.py 1.0.1    <- sube de versión, compila, publica y avisa
    python publicar_launcher.py          <- usa la versión que ya tiene launcher.py (APP_VERSION)

Qué hace:
  1. Cambia APP_VERSION en launcher.py (si le pasas un número).
  2. Compila dist/RancioLaunch.exe con PyInstaller (launcher.spec).
  3. Sube el .exe como Release de GitHub (con la herramienta 'gh'; si no la tienes,
     te pide subirlo a mano en la web).
  4. Anota la versión, el link y el hash en publicar/manifest.json y hace commit + push.

Desde ese momento, cada launcher que se abra con internet detecta la versión nueva,
la descarga y se reinicia solo.
"""
import json
import os
import re
import shutil
import subprocess
import sys

from generar_manifest import sha256

AQUI = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(AQUI, "launcher.py")
MANIFEST = os.path.join(AQUI, "publicar", "manifest.json")
EXE = os.path.join(AQUI, "dist", "RancioLaunch.exe")


def git(*args):
    return subprocess.run(["git", *args], cwd=AQUI, capture_output=True, text=True)


def repo_github():
    r = git("remote", "get-url", "origin")
    if r.returncode != 0:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?\s*$", r.stdout.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def tupla(v):
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).lstrip("vV").split("."))


def leer_version():
    with open(LAUNCHER, encoding="utf-8") as f:
        m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit('No encontré APP_VERSION = "..." en launcher.py')
    return m.group(1)


def escribir_version(v):
    with open(LAUNCHER, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r'^(APP_VERSION\s*=\s*)"[^"]+"', lambda m: f'{m.group(1)}"{v}"', s, flags=re.M)
    with open(LAUNCHER, "w", encoding="utf-8") as f:
        f.write(s)


def main():
    nueva = sys.argv[1].lstrip("vV") if len(sys.argv) > 1 else None
    if nueva and not re.fullmatch(r"\d+(\.\d+)*", nueva):
        sys.exit(f"Versión inválida: '{nueva}'. Usa algo como 1.0.1")
    version = nueva or leer_version()

    repo = repo_github()
    if not repo:
        sys.exit("No pude deducir el repo de GitHub (revisa el remote 'origin').")

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    previa = (manifest.get("launcher") or {}).get("version")
    if previa and tupla(version) <= tupla(previa):
        sys.exit(f"La versión {version} no es mayor que la ya publicada ({previa}).\n"
                 f"Usa: python publicar_launcher.py <número más nuevo>")

    if nueva:
        escribir_version(nueva)
    print(f"1) Versión del launcher: {version}")

    print("2) Compilando .exe (puede tardar un rato)...")
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "launcher.spec"], cwd=AQUI)
    if r.returncode != 0 or not os.path.isfile(EXE):
        sys.exit("Falló la compilación con PyInstaller.")

    tag = f"v{version}"
    url = f"https://github.com/{repo}/releases/download/{tag}/RancioLaunch.exe"

    print(f"3) Subiendo el .exe a GitHub Releases ({tag})...")
    if shutil.which("gh"):
        r = subprocess.run(
            ["gh", "release", "create", tag, EXE, "--title", f"RancioLaunch {version}",
             "--notes", f"Launcher {version}"], cwd=AQUI)
        if r.returncode != 0:
            sys.exit("Falló 'gh release create'. ¿Hiciste 'gh auth login'?")
    else:
        print(f"   No tienes la herramienta 'gh'. Súbelo a mano:\n"
              f"   - Entra a https://github.com/{repo}/releases/new\n"
              f"   - Tag: {tag}  |  Adjunta: {EXE}\n"
              f"   - Pulsa 'Publish release'")
        input("   Cuando esté publicado, presiona Enter para continuar...")

    print("4) Actualizando manifest.json y subiéndolo...")
    manifest["launcher"] = {
        "version": version,
        "url": url,
        "sha256": sha256(EXE),
        "size": os.path.getsize(EXE),
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    git("add", "publicar/manifest.json")
    c = git("commit", "-m", f"Launcher {version}")
    if c.returncode != 0:
        sys.exit(c.stdout + c.stderr)
    p = git("push")
    if p.returncode != 0 and "upstream" in p.stderr:
        rama = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        p = git("push", "-u", "origin", rama)
    if p.returncode != 0:
        sys.exit("Falló el push:\n" + p.stdout + p.stderr)
    print(f"\nListo: launcher {version} publicado. GitHub puede tardar unos minutos en reflejarlo.")


if __name__ == "__main__":
    main()
