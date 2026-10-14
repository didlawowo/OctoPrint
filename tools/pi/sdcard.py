#!/usr/bin/env python3
"""Optional Linux raw flasher. Interactive only; no automatic unmount, no --yes."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys

from image import CHUNK, IMAGE, verify_image

BLKGETSIZE64 = 0x80081272
BLKFLSBUF = 0x1261


def devices() -> list[dict]:
    result = subprocess.run(
        ['lsblk', '--json', '--bytes', '--paths', '--output',
         'NAME,PATH,TYPE,RM,RO,SIZE,MOUNTPOINTS,MODEL,SERIAL'],
        check=True, text=True, capture_output=True,
    )
    return json.loads(result.stdout)['blockdevices']


def validate_device(entries: list[dict], target: str, image_size: int) -> dict:
    selected = next((entry for entry in entries if entry.get('path') == target), None)
    if selected is None or selected.get('type') != 'disk':
        raise RuntimeError('Sélectionner un disque entier, jamais une partition.')
    if selected.get('rm') not in (True, 1) or selected.get('ro') not in (False, 0):
        raise RuntimeError('Seuls les disques amovibles inscriptibles sont autorisés.')
    if int(selected.get('size', 0)) < image_size:
        raise RuntimeError('La carte est plus petite que l’image.')

    def inspect(entry: dict) -> None:
        if any(entry.get('mountpoints') or []):
            raise RuntimeError('Disque ou partition monté(e), y compris swap : démonter avant le flash.')
        for child in entry.get('children', []):
            if child.get('type') != 'part':
                raise RuntimeError('Disque utilisé par LVM, RAID ou un autre périphérique : refus.')
            inspect(child)

    inspect(selected)
    return selected


def identity(entry: dict) -> tuple:
    return tuple(entry.get(key) for key in ('path', 'size', 'model', 'serial', 'rm', 'ro'))


def flash(image: Path, target: str, dry_run: bool = False) -> None:
    if sys.platform != 'linux':
        raise RuntimeError('Le flash brut est réservé à Linux. Utiliser task pi:flash (Imager).')
    expected = verify_image(image)
    if not target or str(Path(target).resolve()) != target:
        raise RuntimeError('Chemin absolu réel du périphérique requis, sans lien symbolique.')
    device_stat = os.stat(target)
    if not stat.S_ISBLK(device_stat.st_mode):
        raise RuntimeError('La cible doit être un périphérique bloc, pas un fichier.')
    entry = validate_device(devices(), target, image.stat().st_size)
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    print(f'IMAGE : {image}\nSHA256 : {expected}\nEFFACEMENT COMPLET : {target}')
    if dry_run:
        print('Simulation uniquement : aucune ouverture en écriture.')
        return
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise RuntimeError('Exécuter avec sudo dans un terminal interactif. Aucun mode automatique.')
    phrase = f'EFFACER {target}'
    if input(f'Taper exactement « {phrase} » pour continuer : ').strip() != phrase:
        raise RuntimeError('Confirmation incorrecte : opération annulée.')
    current = validate_device(devices(), target, image.stat().st_size)
    if identity(current) != identity(entry) or os.stat(target).st_rdev != device_stat.st_rdev:
        raise RuntimeError('Le périphérique a changé après confirmation.')
    # O_EXCL refuses mounted/in-use block devices; O_NOFOLLOW closes a symlink race.
    fd = os.open(target, os.O_RDWR | os.O_EXCL | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r+b', buffering=0) as disk, image.open('rb') as source:
        size = struct.unpack('Q', fcntl.ioctl(disk.fileno(), BLKGETSIZE64, bytes(8)))[0]
        if size != int(entry['size']) or os.fstat(disk.fileno()).st_rdev != device_stat.st_rdev:
            raise RuntimeError('Identité/taille du disque modifiée : refus.')
        written = 0
        total = image.stat().st_size
        source_digest = hashlib.sha256()
        for block in iter(lambda: source.read(CHUNK), b''):
            source_digest.update(block)
            view = memoryview(block)
            while view:
                count = disk.write(view)
                if not count:
                    raise OSError('Écriture interrompue.')
                view = view[count:]
            written += len(block)
            print(f'\rÉcriture : {written * 100 // total} %', end='', flush=True)
        os.fsync(disk.fileno())
        if source_digest.hexdigest() != expected:
            raise RuntimeError('L’image source a changé pendant le flash. Ne pas démarrer cette SD.')
        print('\nVérification intégrale de la lecture…', flush=True)
        fcntl.ioctl(disk.fileno(), BLKFLSBUF, 0)
        disk.seek(0)
        digest = hashlib.sha256()
        remaining = total
        while remaining:
            block = disk.read(min(CHUNK, remaining))
            if not block:
                raise OSError('Lecture de vérification incomplète.')
            digest.update(block)
            remaining -= len(block)
        if digest.hexdigest() != expected:
            raise RuntimeError('Échec de vérification de la SD. Ne pas la démarrer.')
    print('Flash vérifié. Éjecter la carte proprement avant de la retirer.')
    print('Le flash brut ne configure pas Wi-Fi/utilisateur/SSH : utiliser Imager pour un premier démarrage headless.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--image', type=Path, default=IMAGE)
    parser.add_argument('--device')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if args.list:
            print(json.dumps(devices(), indent=2, ensure_ascii=False))
        elif not args.device:
            raise RuntimeError('DEVICE obligatoire. Lister avec task pi:devices, ou utiliser task pi:flash.')
        else:
            flash(args.image.resolve(), args.device, args.dry_run)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Erreur : {error}\n')


if __name__ == '__main__':
    main()
