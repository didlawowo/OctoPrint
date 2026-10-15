#!/usr/bin/env python3
"""Launch the Linux image builder locally or over SSH, then fetch verified output."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import image

REPOSITORY = "https://github.com/didlawowo/OctoPrint.git"
SSH_OPTIONS = [
    "-T",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=4",
    "-o",
    "ForwardAgent=no",
]
ARTIFACTS = ("octopi-atelier.img", "octopi-atelier.img.sha256", "build.json")
RECEIPT = "remote-build.json"
PREFLIGHT = """set -eu
command -v git >/dev/null
command -v docker >/dev/null
python3 - <<'PYCHECK'
import platform, shutil, subprocess, sys
from pathlib import Path
if sys.version_info < (3, 10):
    raise SystemExit('Python >=3.10 requis sur le serveur de build.')
if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
    raise SystemExit('Le serveur SSH doit être Linux x86_64.')
if shutil.disk_usage(Path.home()).free < 20 * 1024**3:
    raise SystemExit('Au moins 20 Gio libres requis dans le home distant.')
result = subprocess.run(['docker', 'info', '--format', '{{.OSType}}'],
                        check=True, text=True, capture_output=True)
if result.stdout.strip() != 'linux':
    raise SystemExit('Un moteur Docker Linux accessible sans sudo est requis.')
print('Prérequis SSH / Python / Git / Docker / espace disque : OK', flush=True)
PYCHECK
"""


def target(mode: str, host: str) -> str:
    if mode == "local":
        return "local"
    if (
        mode == "auto"
        and sys.platform == "linux"
        and platform.machine().lower() in {"x86_64", "amd64"}
    ):
        return "local"
    if not isinstance(host, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host
    ):
        raise ValueError(
            "BUILD_HOST doit être un alias SSH ou utilisateur@hôte, sans options."
        )
    return host


def ssh(host: str, script: str, *, capture: bool = False, output=None):
    # Quote all remote arguments too: OpenSSH invokes a shell on the other end.
    command = ["ssh", *SSH_OPTIONS, host, shlex.join(["sh", "-c", script])]
    result = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE if capture else output,
        text=output is None,
    )
    return result.stdout.strip() if capture else None


def source(committed: bool) -> tuple[str, str]:
    commit = image.run("git", "rev-parse", "HEAD", capture=True)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Commit Git invalide.")
    branch = image.run("git", "symbolic-ref", "--short", "HEAD", capture=True)
    image.run("git", "check-ref-format", "--branch", branch, capture=True)
    if image.run("git", "status", "--porcelain", capture=True):
        if not committed:
            raise RuntimeError(
                "Des changements locaux ne sont pas committés. Les committer/pousser, "
                "ou utiliser BUILD_COMMITTED=1 pour construire uniquement HEAD "
                "sans les envoyer ni les supprimer."
            )
        print(
            "Attention : construction du commit HEAD uniquement ; changements locaux exclus.",
            flush=True,
        )
    return commit, branch


def validate_receipt(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Métadonnées du build distant invalides.")
    target("ssh", data.get("host", ""))
    if not isinstance(data.get("commit"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", data["commit"]
    ):
        raise ValueError("Commit distant invalide.")
    path = data.get("directory", "")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or any(ord(c) < 32 for c in path)
        or ".." in Path(path).parts
        or not Path(path).name.startswith("build-")
    ):
        raise ValueError("Répertoire du build distant invalide.")
    return data


def fetch(data: dict) -> None:
    data = validate_receipt(data)
    image.OUTPUT.mkdir(parents=True, exist_ok=True)
    # Keep the old image intact when a transfer or checksum verification fails.
    with tempfile.TemporaryDirectory(prefix="download-", dir=image.OUTPUT) as tmp:
        staged = Path(tmp)
        remote_output = data["directory"] + "/source/build/atelier-pi/"
        for name in ARTIFACTS:
            print(f"Rapatriement : {name}", flush=True)
            with (staged / name).open("wb") as stream:
                ssh(
                    data["host"], shlex.join(["cat", remote_output + name]), output=stream
                )
        digest = image.verify_image(staged / ARTIFACTS[0])
        metadata = json.loads((staged / "build.json").read_text(encoding="utf-8"))
        if (
            metadata.get("commit") != data["commit"]
            or metadata.get("image_sha256") != digest
        ):
            raise RuntimeError("Image reçue non conforme au commit ou au SHA256 annoncé.")
        for name in ARTIFACTS:
            (staged / name).replace(image.OUTPUT / name)
        image.write_manifest(image.IMAGE, digest)
    print(
        f"Image vérifiée sur ce poste : {image.IMAGE}\nFlasher ici : task pi:flash",
        flush=True,
    )


def remote_build(host: str, committed: bool) -> None:
    if not shutil.which("ssh") or not shutil.which("git"):
        raise RuntimeError("Git et le client OpenSSH sont requis sur le poste local.")
    commit, branch = source(committed)
    print(f"Build Linux délégué à {host}, commit {commit}.", flush=True)
    ssh(host, PREFLIGHT)
    # No existing checkout on the server is modified; no credentials are forwarded.
    create = (
        "from pathlib import Path; import tempfile; "
        "p=Path.home()/'.cache'/'octoprint-atelier'; p.mkdir(parents=True,exist_ok=True); "
        "print(tempfile.mkdtemp(prefix='build-',dir=p))"
    )
    directory = ssh(host, shlex.join(["python3", "-c", create]), capture=True)
    data = validate_receipt({"host": host, "directory": directory, "commit": commit})
    image.OUTPUT.mkdir(parents=True, exist_ok=True)
    (image.OUTPUT / RECEIPT).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    checkout = directory + "/source"
    script = "\n".join(
        [
            "set -eu",
            shlex.join(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    REPOSITORY,
                    checkout,
                ]
            ),
            "cd " + shlex.quote(checkout),
            shlex.join(["git", "fetch", "--tags", "origin", commit]),
            shlex.join(["git", "checkout", "-B", branch, commit]),
            'test "$(git rev-parse HEAD)" = ' + shlex.quote(commit),
            "exec env PYTHONUNBUFFERED=1 python3 tools/pi/image.py build",
        ]
    )
    print(
        f"Dossier distant isolé : {directory}\nLe commit doit être poussé sur le fork.",
        flush=True,
    )
    try:
        ssh(host, script)
        fetch(data)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        print(
            f"Build conservé sur {host}:{directory}. "
            "Si l’image est terminée, reprendre le transfert avec task pi:fetch.",
            file=sys.stderr,
        )
        raise
    # Do not remove potentially root-owned/mounted CustoPiZer directories remotely.
    print(f"Copie distante conservée pour diagnostic : {host}:{directory}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "build", "fetch"])
    parser.add_argument("--mode", choices=["auto", "local", "ssh"], default="auto")
    parser.add_argument("--host", default="nvidia")
    parser.add_argument("--committed", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "fetch":
            fetch(json.loads((image.OUTPUT / RECEIPT).read_text(encoding="utf-8")))
            return
        selected = target(args.mode, args.host)
        if selected == "local" and args.mode != "ssh":
            if args.command == "prepare":
                image.prepare()
            else:
                image.build()
        elif args.command == "prepare":
            ssh(selected, PREFLIGHT)
        else:
            remote_build(selected, args.committed)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Erreur : {error}\n")


if __name__ == "__main__":
    main()
