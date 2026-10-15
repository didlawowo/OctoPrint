#!/usr/bin/env python3
"""Build an OctoPi image containing this checkout; never writes a block device."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "build" / "atelier-pi"
IMAGE = OUTPUT / "octopi-atelier.img"
BASE_URL = (
    "https://github.com/OctoPrint/OctoPi-UpToDate/releases/download/"
    "1.1.0-1.11.8-20260623094920/octopi-1.1.0-1.11.8-20260623094920.zip"
)
BASE_SHA256 = "5cfb364cee2c4d73e6b16db2297bbc5f86895e840820f135d9832a002442fdc2"
BUILDER = "ghcr.io/octoprint/custopizer:latest"
CHUNK = 8 * 1024 * 1024


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_image(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"Image absente : {path}. Exécuter task pi:build.")
    checksum = path.with_suffix(path.suffix + ".sha256")
    if not checksum.is_file():
        raise RuntimeError(f"Somme de contrôle absente : {checksum}")
    fields = checksum.read_text(encoding="utf-8").split()
    if (
        not fields
        or len(fields[0]) != 64
        or any(c not in "0123456789abcdef" for c in fields[0])
    ):
        raise RuntimeError("Somme de contrôle SHA256 invalide.")
    expected = fields[0]
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError("SHA256 de l’image incorrect : aucun flash autorisé.")
    return actual


def prepare() -> None:
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError(
            "Le build CustoPiZer est prévu sur un hôte Linux x86_64 avec Docker."
        )
    missing = [name for name in ("git", "docker") if not shutil.which(name)]
    if missing:
        raise RuntimeError("Installer les prérequis manquants : " + ", ".join(missing))
    if run("docker", "info", "--format", "{{.OSType}}", capture=True) != "linux":
        raise RuntimeError("Un moteur Docker Linux accessible est requis.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(OUTPUT).free < 20 * 1024**3:
        raise RuntimeError(
            "Prévoir au moins 20 Gio libres pour les images intermédiaires."
        )
    print(
        "Prérequis OK. Le build utilise le conteneur officiel CustoPiZer en mode privileged."
    )
    print("Aucun disque physique n’est choisi ni flashé par le build.")


def download_base(destination: Path) -> None:
    if destination.is_file() and sha256(destination) == BASE_SHA256:
        return
    temporary = destination.with_suffix(".part")
    print("Téléchargement de l’image OctoPi officielle épinglée…", flush=True)
    request = urllib.request.Request(
        BASE_URL, headers={"User-Agent": "OctoPrint-Atelier-image-builder"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as source,
            temporary.open("wb") as target,
        ):
            shutil.copyfileobj(source, target, CHUNK)
        if sha256(temporary) != BASE_SHA256:
            raise RuntimeError("SHA256 de l’archive OctoPi incorrect.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def extract_image(archive: Path, destination: Path) -> None:
    # Copy the selected stream; never extract archive-controlled paths.
    with zipfile.ZipFile(archive) as source:
        images = [
            entry
            for entry in source.infolist()
            if entry.filename.endswith(".img") and not entry.is_dir()
        ]
        if len(images) != 1 or not 1024**2 <= images[0].file_size <= 16 * 1024**3:
            raise RuntimeError(
                "Archive OctoPi inattendue : une seule image de 1 Mio à 16 Gio est requise."
            )
        with source.open(images[0]) as stream, destination.open("wb") as target:
            shutil.copyfileobj(stream, target, CHUNK)


def imager_manifest(image: Path, checksum: str) -> dict:
    return {
        "os_list": [
            {
                "name": "OctoPrint Atelier — fork français",
                "description": "Interface mobile/tablette du fork sur OctoPi 1.1.0 (Bookworm). Cible : Raspberry Pi 4.",
                "url": image.resolve().as_uri(),
                "release_date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
                "image_download_size": image.stat().st_size,
                "extract_size": image.stat().st_size,
                "extract_sha256": checksum,
                "init_format": "systemd",
            }
        ]
    }


def write_manifest(image: Path, checksum: str) -> Path:
    manifest = image.parent / "atelier.rpi-imager-manifest"
    manifest.write_text(
        json.dumps(imager_manifest(image, checksum), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def build() -> None:
    prepare()
    if run("git", "status", "--porcelain", capture=True):
        raise RuntimeError(
            "Le checkout doit être propre : committer les changements avant le build (git archive HEAD)."
        )
    commit = run("git", "rev-parse", "HEAD", capture=True)
    base = OUTPUT / "base-octopi.zip"
    download_base(base)
    run("docker", "pull", BUILDER)
    digests = json.loads(
        run(
            "docker",
            "image",
            "inspect",
            BUILDER,
            "--format",
            "{{json .RepoDigests}}",
            capture=True,
        )
    )
    builder = next(
        (
            item
            for item in digests
            if item.startswith("ghcr.io/octoprint/custopizer@sha256:")
        ),
        None,
    )
    if not builder:
        raise RuntimeError("Impossible de figer le digest du conteneur CustoPiZer.")
    workspace = Path(tempfile.mkdtemp(prefix="work-", dir=OUTPUT))
    try:
        scripts = workspace / "scripts"
        files = scripts / "files"
        files.mkdir(parents=True)
        extract_image(base, workspace / "input.img")
        run(
            "git",
            "archive",
            "--format=tar",
            "--prefix=source/",
            "--output=" + str(files / "source.tar"),
            "HEAD",
        )
        shutil.copy2(ROOT / "tools/pi/01-install-fork", scripts / "01-install-fork")
        (scripts / "01-install-fork").chmod(0o755)
        config = workspace / "config.local"
        config.write_text(
            "EDITBASE_IMAGE_ENLARGEROOT=2048\nEDITBASE_IMAGE_RESIZEROOT=512\n",
            encoding="utf-8",
        )
        print(
            f"Installation du commit {commit} dans l’image. Cela peut prendre plusieurs minutes.",
            flush=True,
        )
        run(
            "docker",
            "run",
            "--rm",
            "--privileged",
            "--platform",
            "linux/amd64",
            "-v",
            f"{workspace}:/CustoPiZer/workspace",
            "-v",
            f"{config}:/CustoPiZer/config.local:ro",
            builder,
        )
        result = workspace / "output.img"
        if not result.is_file() or result.stat().st_size < 1024**2:
            raise RuntimeError("CustoPiZer n’a pas produit une image exploitable.")
        digest = sha256(result)
        result.replace(IMAGE)
        IMAGE.with_suffix(".img.sha256").write_text(
            f"{digest}  {IMAGE.name}\n", encoding="utf-8"
        )
        metadata = {
            "commit": commit,
            "base_url": BASE_URL,
            "base_sha256": BASE_SHA256,
            "builder": builder,
            "image_sha256": digest,
            "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        (OUTPUT / "build.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest(IMAGE, digest)
        print(
            f"Image prête : {IMAGE}\nSHA256 : {digest}\nFlasher/configurer : task pi:flash"
        )
    finally:
        # The official privileged builder may leave root-owned files; do not broaden permissions.
        try:
            shutil.rmtree(workspace)
        except PermissionError:
            print(
                f"Nettoyage manuel requis pour les intermédiaires appartenant à root : {workspace}",
                file=sys.stderr,
            )


def imager(image: Path) -> None:
    checksum = verify_image(image)
    manifest = write_manifest(image, checksum)
    executable = (
        os.environ.get("RPI_IMAGER")
        or shutil.which("rpi-imager")
        or shutil.which("rpi-imager.exe")
    )
    mac_binary = Path("/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager")
    if not executable and mac_binary.is_file():
        executable = str(mac_binary)
    if not executable:
        raise RuntimeError(
            f"Installer Raspberry Pi Imager, puis ouvrir {manifest}, ou définir RPI_IMAGER."
        )
    print(
        "Dans Imager : choisir la SD, configurer Wi-Fi/Ethernet, utilisateur et SSH, puis confirmer l’effacement."
    )
    run(executable, "--repo", str(manifest))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "build", "imager"])
    parser.add_argument("--image", type=Path, default=IMAGE)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare()
        elif args.command == "build":
            build()
        else:
            imager(args.image.resolve())
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as error:
        parser.exit(1, f"Erreur : {error}\n")


if __name__ == "__main__":
    main()
