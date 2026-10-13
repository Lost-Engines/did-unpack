# SPDX-License-Identifier: GPL-3.0-or-later
import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from did_unpack import (Archive, FormatError, canonical_name, decompress_ra,
                        main, recover_names, tfx_hash, verify_reference_names, write_extraction)

# A small RA v2 stream with one literal run. Also checked with the C reference.
LITERAL_ABC = bytes.fromhex('5241000203000000007d0000010100014001fe010500616263')


def archive_bytes(resources=(b'abc',), identifiers=(0x12345678,),
                  directories=('tunes\\',), extensions=('.adl',), tail=b''):
    data = b''.join(resources)
    names = b''.join(bytes((len(n),)) + n.encode('ascii') for n in (*directories, *extensions))
    index = struct.pack('<4H', len(resources), len(directories), len(extensions), len(names)) + names
    offset = 4
    for identifier, resource in zip(identifiers, resources):
        index += struct.pack('<III', identifier, offset, len(resource))
        offset += len(resource)
    return struct.pack('<I', 4 + len(data)) + data + index + tail


class DecompressionTests(unittest.TestCase):
    def test_golden_literal_run(self):
        self.assertEqual(decompress_ra(LITERAL_ABC), b'abc')

    def test_truncated_streams(self):
        for end in range(len(LITERAL_ABC)):
            with self.subTest(end=end), self.assertRaises(FormatError):
                decompress_ra(LITERAL_ABC[:end])

    def test_declared_size_checks(self):
        for size in (2, 4):
            data = LITERAL_ABC[:4] + struct.pack('<I', size) + LITERAL_ABC[8:]
            with self.assertRaises(FormatError):
                decompress_ra(data)
        with self.assertRaisesRegex(FormatError, 'exceeds limit'):
            decompress_ra(LITERAL_ABC, max_size=2)

    def test_wrong_version(self):
        with self.assertRaises(FormatError):
            decompress_ra(b'RA\x00\x01' + LITERAL_ABC[4:])


class ArchiveTests(unittest.TestCase):
    def test_payloads_and_trailer(self):
        archive = Archive(archive_bytes(resources=(b'RANK\n', LITERAL_ABC),
                                      identifiers=(1, 2), tail=b'\x03\xb1\xff\xff'))
        self.assertEqual(archive.directories, ['tunes\\'])
        self.assertEqual(archive.extensions, ['.adl'])
        self.assertEqual(archive.unpack(archive.entries[0]), b'RANK\n')
        self.assertEqual(archive.unpack(archive.entries[1]), b'abc')
        self.assertEqual(archive.trailing, b'\x03\xb1\xff\xff')

    def test_bad_index_offset(self):
        for pointer in (0, 3, 0xffffffff):
            with self.assertRaises(FormatError):
                Archive(struct.pack('<I', pointer) + b'\x00' * 16)

    def test_payload_out_of_bounds(self):
        data = bytearray(archive_bytes())
        data[-8:-4] = struct.pack('<I', 0xffffff00)
        with self.assertRaisesRegex(FormatError, 'resource area'):
            Archive(bytes(data))

    def test_truncated_index(self):
        with self.assertRaises(FormatError):
            Archive(archive_bytes()[:-1])

    def test_name_table_length(self):
        data = bytearray(archive_bytes())
        offset = struct.unpack_from('<I', data)[0]
        data[offset + 8] = 255
        with self.assertRaises(FormatError):
            Archive(bytes(data))


class FilenameTests(unittest.TestCase):
    def test_real_tfx_hashes(self):
        # Independent known payloads matched to IDs in the September TFX archive.
        self.assertEqual(tfx_hash('Dintrob'), 0x72de1438)
        self.assertEqual(tfx_hash('Dintroc'), 0x73df1538)
        self.assertEqual(tfx_hash('Dintroe'), 0x75e11338)
        self.assertEqual(tfx_hash('8miss830V'), 0x955faaa1)
        self.assertEqual(tfx_hash('Lmig_29l'), 0x80bf3e23)

    def test_directory_extension_substitution(self):
        archive = Archive(archive_bytes())
        self.assertEqual(archive.short_name('TUNES/INTRO.ADL'), '0introA')
        self.assertEqual(archive.short_name('intro.other'), 'introother')

    def test_name_matching(self):
        template = Archive(archive_bytes())
        identifier = template.hash_name('tunes/intro.adl')
        archive = Archive(archive_bytes(identifiers=(identifier,)))
        matches = recover_names(archive, [b'intro.adl\r\n'])
        self.assertEqual(matches[identifier], ['tunes/intro.adl'])

    def test_reference_names_require_matching_contents(self):
        template = Archive(archive_bytes())
        identifier = template.hash_name('tunes/intro.adl')
        archive = Archive(archive_bytes(resources=(LITERAL_ABC,), identifiers=(identifier,)))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'tunes/intro.adl'
            path.parent.mkdir()
            path.write_bytes(LITERAL_ABC)
            self.assertEqual(verify_reference_names(archive, [b'abc'], [root]),
                             {identifier: ['tunes/intro.adl']})
            path.write_bytes(b'abc')
            self.assertEqual(verify_reference_names(archive, [b'abc'], [root]),
                             {identifier: ['tunes/intro.adl']})
            path.write_bytes(b'wrong')
            self.assertEqual(verify_reference_names(archive, [b'abc'], [root]), {})

    def test_unsafe_paths(self):
        for name in ('/etc/passwd', '../file', 'a/../file', 'c:\\file',
                     'a//b', 'a\x00b', 'a?b'):
            with self.subTest(name=name), self.assertRaises(FormatError):
                canonical_name(name)


class ExtractionTests(unittest.TestCase):
    def test_unknown_and_ambiguous_names_are_preserved(self):
        archive = Archive(archive_bytes(resources=(b'one', b'two'), identifiers=(1, 2)))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            manifest = write_extraction(archive, [b'one', b'two'], out, {2: ['first.adl', 'second.adl']})
            self.assertEqual([e['name_status'] for e in manifest['entries']], ['unknown', 'ambiguous'])
            self.assertEqual(sorted(p.read_bytes() for p in (out / '_unknown').iterdir()), [b'one', b'two'])
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['entries'][1]['candidate_names'],
                             ['first.adl', 'second.adl'])

    def test_verified_names_resolve_guesses_without_losing_them(self):
        archive = Archive(archive_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = write_extraction(archive, [b'abc'], out,
                                      {0x12345678: ['guess.adl', 'real.adl']},
                                      verified={0x12345678: ['real.adl']})
            record = result['entries'][0]
            self.assertEqual(record['path'], 'real.adl')
            self.assertEqual(record['name_status'], 'verified')
            self.assertEqual(record['candidate_names'], ['guess.adl', 'real.adl'])

    def test_never_overwrites_existing_output(self):
        archive = Archive(archive_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'important').write_text('keep')
            with self.assertRaises(FormatError):
                write_extraction(archive, [b'abc'], out, {})
            self.assertEqual((out / 'important').read_text(), 'keep')

    def test_duplicate_identifiers_do_not_overwrite(self):
        archive = Archive(archive_bytes(resources=(b'one', b'two'), identifiers=(1, 1)))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            manifest = write_extraction(archive, [b'one', b'two'], out, {1: ['same.adl']})
            self.assertNotEqual(manifest['entries'][0]['path'], manifest['entries'][1]['path'])
            self.assertEqual((out / 'same.adl').read_bytes(), b'one')

    def test_manifest_filename_does_not_overwrite_a_resource(self):
        archive = Archive(archive_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = write_extraction(archive, [b'abc'], out, {0x12345678: ['manifest.json']})
            self.assertNotEqual(result['entries'][0]['path'], 'manifest.json')

    def test_extraction_rechecks_supplied_paths(self):
        archive = Archive(archive_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaises(FormatError):
                write_extraction(archive, [b'abc'], out, {0x12345678: ['../escape']})
            self.assertFalse(out.exists())

    def test_raw_manifest_and_bytes(self):
        archive = Archive(archive_bytes(resources=(LITERAL_ABC,)))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = write_extraction(archive, [LITERAL_ABC], out, {}, raw=True)
            record = result['entries'][0]
            self.assertIsNone(record['decoded_size'])
            self.assertEqual((out / record['path']).read_bytes(), LITERAL_ABC)

    def test_cli_reports_errors_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'DID.DAT'
            bad.write_bytes(b'bad')
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main([str(bad), str(Path(tmp) / 'out')])
            self.assertEqual(result, 1)
            self.assertIn('ERROR:', stderr.getvalue())
            self.assertFalse((Path(tmp) / 'out').exists())


if __name__ == '__main__':
    unittest.main()
