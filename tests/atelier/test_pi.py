"""Pure tests: never invoke Docker, sudo, mount, or a physical block-device write."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'pi'))
import image  # noqa: E402
import sdcard  # noqa: E402


def disk(**overrides):
    result = {'path': '/dev/sdb', 'type': 'disk', 'rm': True, 'ro': False,
              'size': 8 * 1024**3, 'mountpoints': [None], 'model': 'SD reader',
              'serial': 'test-123', 'children': []}
    result.update(overrides)
    return result


class DeviceSafetyTests(unittest.TestCase):
    def test_accept_unmounted_removable_whole_disk(self):
        self.assertEqual(sdcard.validate_device([disk()], '/dev/sdb', 1024)['path'], '/dev/sdb')

    def test_reject_system_disks_and_read_only_devices(self):
        for overrides in ({'rm': False}, {'ro': True}, {'rm': None}, {'ro': None}):
            with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                sdcard.validate_device([disk(**overrides)], '/dev/sdb', 1024)

    def test_reject_partition_unknown_and_too_small_devices(self):
        for entries, target, size in [([disk(type='part')], '/dev/sdb', 1),
                                      ([disk()], '/dev/sdb1', 1),
                                      ([disk(size=1)], '/dev/sdb', 2)]:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                sdcard.validate_device(entries, target, size)

    def test_reject_all_mounts_including_swap_and_root(self):
        for mount in ('/', '/boot', '[SWAP]', '/run/media/test/bootfs'):
            with self.subTest(mount=mount), self.assertRaises(RuntimeError):
                sdcard.validate_device([disk(children=[{'type': 'part', 'mountpoints': [mount]}])], '/dev/sdb', 1)

    def test_reject_lvm_raid_and_other_consumers(self):
        for kind in ('lvm', 'raid1', 'crypt', 'mpath'):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                sdcard.validate_device([disk(children=[{'type': kind, 'mountpoints': []}])], '/dev/sdb', 1)

    def test_identity_detects_device_replacement(self):
        self.assertNotEqual(sdcard.identity(disk()), sdcard.identity(disk(serial='other')))
        self.assertNotEqual(sdcard.identity(disk()), sdcard.identity(disk(size=1)))

    def test_regular_file_is_never_opened_as_flash_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'not-a-device'
            target.write_bytes(b'keep me')
            with patch.object(sdcard, 'verify_image', return_value='fake'), self.assertRaises(RuntimeError):
                sdcard.flash(Path(tmp) / 'image.img', str(target))
            self.assertEqual(target.read_bytes(), b'keep me')


class ImageBuildTests(unittest.TestCase):
    def test_checksum_required_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'image.img'
            path.write_bytes(b'known image')
            with self.assertRaises(RuntimeError):
                image.verify_image(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.with_suffix('.img.sha256').write_text(digest + '  image.img\n')
            self.assertEqual(image.verify_image(path), digest)
            path.write_bytes(b'modified')
            with self.assertRaises(RuntimeError):
                image.verify_image(path)

    def test_empty_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'image.img'
            path.write_bytes(b'x')
            path.with_suffix('.img.sha256').write_text('')
            with self.assertRaises(RuntimeError):
                image.verify_image(path)

    def test_imager_manifest_keeps_bookworm_customisation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'my image.img'
            path.write_bytes(b'image')
            manifest = image.imager_manifest(path, 'test')
            item = manifest['os_list'][0]
            self.assertEqual(item['init_format'], 'systemd')
            self.assertIn('my%20image.img', item['url'])
            self.assertEqual(item['extract_size'], 5)
            self.assertEqual(item['extract_sha256'], 'test')
            self.assertNotIn('password', json.dumps(manifest))

    def test_archive_paths_are_never_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            archive = directory / 'base.zip'
            content = b'0' * 1024**2
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as target:
                target.writestr('../../escape.img', content)
            image.extract_image(archive, directory / 'input.img')
            self.assertEqual((directory / 'input.img').read_bytes(), content)
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['base.zip', 'input.img'])

    def test_ambiguous_and_empty_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for count in (0, 2):
                archive = directory / f'{count}.zip'
                with zipfile.ZipFile(archive, 'w') as target:
                    for i in range(count):
                        target.writestr(f'{i}.img', b'x')
                with self.assertRaises(RuntimeError):
                    image.extract_image(archive, directory / 'input.img')

    def test_bad_download_checksum_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'base.zip'
            with patch.object(image.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad')):
                with self.assertRaises(RuntimeError):
                    image.download_base(target)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.part').exists())

    def test_dirty_source_is_not_silently_omitted(self):
        with patch.object(image, 'prepare'), patch.object(image, 'run', return_value=' M source.py') as run:
            with self.assertRaises(RuntimeError):
                image.build()
            run.assert_called_once_with('git', 'status', '--porcelain', capture=True)


if __name__ == '__main__':
    unittest.main()
