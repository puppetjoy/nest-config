#!/usr/bin/env python3
"""Exercise the actual rendered reset filter against disposable host roots."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'templates/cli/reset-filter.rules.epp'


class ResetIdentityFilterTest(unittest.TestCase):
    def test_generic_image_never_replaces_or_deletes_host_identity(self):
        rendered = subprocess.run(
            ['puppet', 'epp', 'render', str(TEMPLATE), '--values', '{"rules" => []}'],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout
        with tempfile.TemporaryDirectory(prefix='nest-reset-identity-') as temporary:
            root = Path(temporary)
            rules = root / 'filter.rules'
            rules.write_text(rendered)
            source, target = root / 'image', root / 'host'
            (source / 'etc').mkdir(parents=True)
            (target / 'etc').mkdir(parents=True)
            hostname, machine = target / 'etc/hostname', target / 'etc/machine-id'
            hostname.write_text('fixture-host\n')
            machine.write_text('a' * 32 + '\n')
            # Empty generic identity must not replace the host's first-boot
            # network matching or pool-bound machine identity. Omission must
            # not delete either file under the real --delete copy semantics.
            for present in (True, False):
                for name in ('hostname', 'machine-id'):
                    image_file = source / 'etc' / name
                    if present:
                        image_file.write_text('')
                    else:
                        image_file.unlink()
                (source / 'etc/payload').write_text('updated payload\n')
                (target / 'etc/obsolete').write_text('must be removed\n')
                subprocess.run(
                    ['rsync', '-a', '--delete', '--checksum',
                     '--filter=merge ' + str(rules), str(source) + '/', str(target) + '/'],
                    check=True, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(hostname.read_text(), 'fixture-host\n')
                self.assertEqual(machine.read_text(), 'a' * 32 + '\n')
                self.assertEqual((target / 'etc/payload').read_text(), 'updated payload\n')
                self.assertFalse((target / 'etc/obsolete').exists())


if __name__ == '__main__':
    unittest.main()
