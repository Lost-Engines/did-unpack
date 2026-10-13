#!/usr/bin/env python3
"""Extract DID resource archives and recover candidate TFX filenames.

SPDX-License-Identifier: GPL-3.0-or-later
RA decoding is adapted from Benjamin Haisch's DecompressRA (2006),
with permission to use it freely provided credit is given. See NOTICE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

RA_MAGIC = b"RA\x00\x02"
DEFAULT_MAX_SIZE = 256 * 1024 * 1024


class FormatError(ValueError):
    """Invalid, unsupported, or truncated archive/resource data."""


class _RAReader:
    """Interleaved bit and byte reads share one cursor, as in the original codec."""

    def __init__(self, data: bytes):
        self.data = data
        self.position = 12
        self.bits = 0
        self.buffer = 0

    def byte(self) -> int:
        if self.position >= len(self.data):
            raise FormatError("truncated RA stream")
        value = self.data[self.position]
        self.position += 1
        return value

    def bit(self) -> int:
        if not self.bits:
            self.buffer = self.byte()
            self.bits = 8
        self.bits -= 1
        return (self.buffer >> self.bits) & 1

    def value(self, bits: int) -> int:
        result = 0
        for _ in range(bits):
            result = (result << 1) | self.bit()
        return result

    def table(self, branches: bytearray, leaves: bytearray) -> None:
        count = self.byte() * 2
        if count > len(branches):
            raise FormatError("RA tree exceeds its table")
        left_bits = self.value(3) + 1
        right_bits = self.value(3) + 1
        for i in range(count):
            if self.bit():
                branches[i] = 0
                leaves[i] = self.value(right_bits)
            else:
                branches[i] = self.value(left_bits)

    def symbol(self, table: tuple[bytearray, bytearray]) -> int:
        branches, leaves = table
        node = 0
        for _ in range(len(branches)):
            index = node * 2 + self.bit()
            if index >= len(branches):
                raise FormatError("invalid RA tree reference")
            node = branches[index]
            if not node:
                return leaves[index]
        raise FormatError("cyclic RA tree")


def decompress_ra(data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> bytes:
    """Decode RA version 2; reject truncation, invalid references and wrong sizes."""
    if data[:4] != RA_MAGIC:
        raise FormatError("expected an RA version 2 resource")
    if len(data) < 13:
        raise FormatError("truncated RA header/stream")
    expected = struct.unpack_from("<I", data, 4)[0]
    if expected > max_size:
        raise FormatError(f"RA output size {expected} exceeds limit {max_size}")
    reader = _RAReader(data)
    counts = (bytearray(512), bytearray(512))
    lengths = (bytearray(512), bytearray(512))
    offsets = (bytearray(32), bytearray(32))
    out = bytearray()
    reader.bit()  # The leading bit is consumed before the first raw block size.
    while True:
        commands = reader.byte() | (reader.byte() << 8)
        reader.table(*lengths)
        reader.table(*counts)
        reader.table(*offsets)
        for _ in range(commands):
            literal_count = reader.symbol(counts)
            end = reader.position + literal_count
            if end > len(data):
                raise FormatError("truncated RA literal run")
            if len(out) + literal_count > expected:
                raise FormatError("RA literal run exceeds declared output size")
            out.extend(data[reader.position:end])
            reader.position = end
            length = reader.symbol(lengths)
            if length == 255:
                length += (reader.value(2) << 8) | reader.byte()
            if length:
                distance = reader.symbol(offsets)
                if distance >= 2:
                    distance = (1 << (distance - 1)) | reader.value(distance - 1)
                distance += 1
                if distance > len(out):
                    raise FormatError("RA match refers before the output buffer")
                if len(out) + length > expected:
                    raise FormatError("RA match exceeds declared output size")
                for _ in range(length):
                    out.append(out[-distance])  # Overlapping matches are intentional.
        if not reader.bit():
            break
    if len(out) != expected:
        raise FormatError(f"RA size mismatch: expected {expected}, decoded {len(out)}")
    return bytes(out)


def tfx_hash(short_name: str) -> int:
    """TFX's byte-wise hash of a name after directory/extension substitution."""
    encoded = short_name.encode("ascii")
    total = accumulated = shifted = rising = 0
    previous = encoded[0] if encoded else 0
    for index, char in enumerate(encoded):
        if index and previous != ord("_"):
            rising = ((rising << 1) | (previous < char)) & 0xFF
        previous = char
        if char == ord("_"):
            shifted = (shifted - index) & 0xFF
        else:
            total = (total + char) & 0xFF
            shifted = ((shifted << 1) ^ char) & 0xFF
            accumulated = (accumulated + total) & 0xFF
    return ((len(encoded) & 15) << 28) | ((total & 15) << 24) | \
        (accumulated << 16) | (shifted << 8) | rising


@dataclass(frozen=True)
class Entry:
    index: int
    identifier: int
    offset: int
    size: int


class Archive:
    """One footer-indexed DID.DAT archive; payloads are independently compressed."""

    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 12:
            raise FormatError("truncated archive")
        self.index_offset = struct.unpack_from("<I", data)[0]
        if not 4 <= self.index_offset <= len(data) - 8:
            raise FormatError("archive index offset is outside the file")
        count, dirs, exts, names_size = struct.unpack_from("<4H", data, self.index_offset)
        position = self.index_offset + 8
        names_end = position + names_size
        entries_end = names_end + count * 12
        if entries_end > len(data):
            raise FormatError("truncated archive index")
        names = []
        for _ in range(dirs + exts):
            if position >= names_end:
                raise FormatError("truncated archive name table")
            length = data[position]
            position += 1
            if position + length > names_end:
                raise FormatError("archive string exceeds name table")
            try:
                name = data[position:position + length].decode("ascii")
            except UnicodeDecodeError as error:
                raise FormatError("non-ASCII archive name table is unsupported") from error
            names.append(name)
            position += length
        if position != names_end:
            raise FormatError("archive name table size does not match its strings")
        self.directories = names[:dirs]
        self.extensions = names[dirs:]
        self.trailing = data[entries_end:]
        entries = []
        for i in range(count):
            identifier, offset, size = struct.unpack_from("<III", data, names_end + i * 12)
            if offset < 4 or offset + size > self.index_offset:
                raise FormatError(f"entry {i}: payload lies outside the resource area")
            entries.append(Entry(i, identifier, offset, size))
        self.entries = entries

    @classmethod
    def read(cls, filename: Path) -> Archive:
        return cls(filename.read_bytes())

    def stored(self, entry: Entry) -> bytes:
        return self.data[entry.offset:entry.offset + entry.size]

    def unpack(self, entry: Entry, max_size: int = DEFAULT_MAX_SIZE) -> bytes:
        data = self.stored(entry)
        if data.startswith(RA_MAGIC):
            return decompress_ra(data, max_size)
        if data.startswith(b"RA\x00"):
            raise FormatError(f"entry {entry.index}: unsupported RA version")
        return data

    def short_name(self, name: str) -> str:
        name = canonical_name(name).replace("/", "\\")
        for index, prefix in enumerate(self.directories):
            if name.startswith(prefix.lower()):
                name = chr(ord("0") + index) + name[len(prefix):]
                break
        dot = name.find(".")
        if dot >= 0:
            extension = name[dot:]
            try:
                code = self.extensions.index(extension)
                name = name[:dot] + chr(ord("A") + code)
            except ValueError:
                name = name[:dot] + name[dot + 1:]
        return name

    def hash_name(self, name: str) -> int:
        return tfx_hash(self.short_name(name))


def canonical_name(name: str) -> str:
    """Normalise DOS names and reject paths that cannot safely be extracted."""
    name = name.strip().replace("\\", "/").lower()
    if not name or name.startswith("/") or ":" in name or "\x00" in name:
        raise FormatError(f"unsafe filename: {name!r}")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise FormatError(f"unsafe filename: {name!r}")
    if any(ord(char) < 32 or ord(char) > 126 for char in name):
        raise FormatError(f"unsupported filename: {name!r}")
    if any(char in '<>"|?*' for char in name):
        raise FormatError(f"unsafe filename: {name!r}")
    return name


# Full file references and short, terminated identifiers from resources/scripts.
FILE_REFERENCES = re.compile(rb"(?<![A-Za-z0-9_\\/])[A-Za-z0-9_\\/]{1,80}\.[A-Za-z0-9]{1,4}(?![A-Za-z0-9_])")
BARE_NAMES = re.compile(rb"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]{1,7}(?=\x00|[\r\n])")


def name_hints(data: bytes) -> tuple[set[str], set[str]]:
    names, stems = set(), set()
    for match in FILE_REFERENCES.finditer(data):
        try:
            name = canonical_name(match.group().decode("ascii"))
        except FormatError:
            continue
        names.add(name)
        base = PurePosixPath(name).name.split(".")[0]
        if 1 <= len(base) <= 8:
            stems.add(base)
    stems.update(match.group().decode("ascii").lower() for match in BARE_NAMES.finditer(data))
    return names, stems


def recover_names(archive: Archive, resources: list[bytes], scans: Sequence[bytes] = (),
                  supplied: Sequence[str] = ()) -> dict[int, list[str]]:
    """Enumerate evidence-based candidates; a hash match does not prove authorship."""
    wanted = {entry.identifier for entry in archive.entries}
    matches: dict[int, set[str]] = defaultdict(set)
    stems = set()
    direct = {canonical_name(name) for name in supplied}
    for data in [*resources, *scans]:
        names, bare = name_hints(data)
        direct.update(names)
        stems.update(bare)
    for name in direct:
        identifier = archive.hash_name(name)
        if identifier in wanted:
            matches[identifier].add(name)
    # Tables are archive-specific; the synthetic codes are case-sensitive.
    prefixes = [("", "")] + [(d.replace("\\", "/").lower(), chr(48 + i))
                              for i, d in enumerate(archive.directories)]
    suffixes = [("", "")] + [(e.lower(), chr(65 + i))
                              for i, e in enumerate(archive.extensions)]
    for stem in sorted(stems):
        for directory, prefix in prefixes:
            for extension, suffix in suffixes:
                short = prefix + stem + suffix
                identifier = tfx_hash(short)
                if identifier in wanted:
                    name = canonical_name(directory + stem + extension)
                    matches[identifier].add(name)
    return {identifier: sorted(names) for identifier, names in matches.items()}


def verify_reference_names(archive: Archive, resources: list[bytes],
                           directories: Sequence[Path]) -> dict[int, list[str]]:
    """Match loose files by both TFX identifier and exact stored/decoded bytes."""
    by_identifier: dict[int, list[tuple[Entry, bytes]]] = defaultdict(list)
    for entry, data in zip(archive.entries, resources):
        by_identifier[entry.identifier].append((entry, data))
    verified: dict[int, set[str]] = defaultdict(set)
    for directory in directories:
        if not directory.is_dir():
            raise FormatError(f"reference is not a directory: {directory}")
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            name = canonical_name(path.relative_to(directory).as_posix())
            identifier = archive.hash_name(name)
            possible = by_identifier.get(identifier, [])
            if not possible:
                continue
            loose = path.read_bytes()
            if all(loose == data or loose == archive.stored(entry) for entry, data in possible):
                verified[identifier].add(name)
    return {identifier: sorted(names) for identifier, names in verified.items()}


def write_extraction(archive: Archive, resources: list[bytes], output: Path,
                     matches: dict[int, list[str]], raw: bool = False,
                     verified: dict[int, list[str]] | None = None) -> dict:
    if output.exists():
        raise FormatError(f"output already exists: {output}; choose a new directory")
    if len(resources) != len(archive.entries):
        raise FormatError("resource count does not match archive index")
    verified = verified or {}
    records = []
    used: set[str] = {"manifest.json"}
    for entry, data in zip(archive.entries, resources):
        confirmed = verified.get(entry.identifier, [])
        names = sorted(set(matches.get(entry.identifier, [])) | set(confirmed))
        choices = confirmed or names
        name = canonical_name(choices[0]) if len(choices) == 1 else None
        path = name or f"_unknown/{entry.identifier:08x}-{entry.index:04d}.bin"
        if path in used:
            path = f"_unknown/{entry.identifier:08x}-{entry.index:04d}.bin"
            name = None
        used.add(path)
        payload = archive.stored(entry) if raw else data
        record = {
            "index": entry.index, "identifier": f"{entry.identifier:08x}",
            "offset": entry.offset, "stored_size": entry.size,
            "decoded_size": None if raw else len(data), "output_size": len(payload), "compression": "ra2" if archive.stored(entry).startswith(RA_MAGIC) else "none",
            "path": path, "candidate_names": names, "verified_names": confirmed,
            "name_status": ("verified" if confirmed else "candidate") if name else "ambiguous" if names else "unknown",
            "stored_sha256": hashlib.sha256(archive.stored(entry)).hexdigest(),
            "output_sha256": hashlib.sha256(payload).hexdigest(),
        }
        records.append((record, payload))
    manifest = {
        "format": "did-unpack-manifest-1", "archive_sha256": hashlib.sha256(archive.data).hexdigest(),
        "index_offset": archive.index_offset, "directories": archive.directories,
        "extensions": archive.extensions, "trailing_bytes_hex": archive.trailing.hex(),
        "raw": raw, "entries": [record for record, _ in records],
    }
    output.mkdir(parents=True)
    for record, payload in records:
        destination = output / record["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", type=Path, help="original DID.DAT resource archive")
    parser.add_argument("output", type=Path, nargs="?", help="new output directory (required unless --list)")
    parser.add_argument("--list", action="store_true", help="list archive entries without extracting")
    parser.add_argument("--scan", type=Path, action="append", default=[], metavar="FILE",
                        help="search an executable or resource for filename hints; repeatable")
    parser.add_argument("--names", type=Path, action="append", default=[], metavar="FILE",
                        help="read candidate DOS paths, one per line; repeatable")
    parser.add_argument("--reference", type=Path, action="append", default=[], metavar="DIR",
                        help="verify names against matching loose files relative to DIR; repeatable")
    parser.add_argument("--no-names", action="store_true", help="extract by identifier without TFX name guessing")
    parser.add_argument("--raw", action="store_true", help="extract stored payloads without decompression")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE, metavar="BYTES",
                        help="maximum decoded size per resource (default: 256 MiB)")
    args = parser.parse_args(argv)
    if not args.list and args.output is None:
        parser.error("specify an output directory or --list")
    if args.max_size < 0:
        parser.error("--max-size must be non-negative")
    try:
        archive = Archive.read(args.archive)
        resources = [archive.stored(e) if args.raw else archive.unpack(e, args.max_size) for e in archive.entries]
        scans = [path.read_bytes() for path in args.scan]
        supplied = [line.strip() for path in args.names for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        matches = {} if args.no_names else recover_names(archive, resources, scans, supplied)
        verified = {} if args.no_names else verify_reference_names(archive, resources, args.reference)
        if args.list:
            for entry in archive.entries:
                names = matches.get(entry.identifier, [])
                names = sorted(set(names) | set(verified.get(entry.identifier, [])))
                confirmed = verified.get(entry.identifier, [])
                choices = confirmed or names
                label = choices[0] if len(choices) == 1 else " | ".join(names) if names else "?"
                if len(confirmed) == 1:
                    label += " [verified]"
                print(f"{entry.identifier:08x}  {entry.size:9d}  {label}")
        else:
            manifest = write_extraction(archive, resources, args.output, matches, args.raw, verified)
            named = sum(e["name_status"] in ("candidate", "verified") for e in manifest["entries"])
            confirmed = sum(e["name_status"] == "verified" for e in manifest["entries"])
            print(f"Extracted {len(archive.entries)} resources to {args.output}; {named} named ({confirmed} verified against loose files).")
            print("All filename candidates, ambiguities and SHA-256 hashes are recorded in manifest.json.")
    except (OSError, ValueError, UnicodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
