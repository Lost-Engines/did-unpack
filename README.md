# did-unpack

A standalone Python extractor for Digital Image Design's `DID.DAT` resource archives, tested with **TFX** and its bundled **Inferno** demo. It decompresses RA version 2 resources and recovers candidate TFX filenames from strings in the resources, the game executable, and supplied filename lists.

**Python 3.10 or later. No packages to install.**

```sh
python3 did_unpack.py /path/to/TFX/DID.DAT unpacked --scan /path/to/TFX/TFX.DAT --reference /path/to/TFX
```

Windows:

```bat
py -3 did_unpack.py C:\TFX\DID.DAT unpacked --scan C:\TFX\TFX.DAT --reference C:\TFX
```

The output directory must be new. It contains the extracted resources and `manifest.json`, which records source offsets, stored/output SHA-256 hashes, compression, filename candidates and unresolved entries.

## Filenames

The archive stores identifiers, directory prefixes and extensions, rather than complete filenames. The tool implements TFX's actual directory/extension substitution and hash algorithm, then checks names found in resource strings and scanned files against the archive identifiers.

**A matching hash is a candidate, not proof of the original name.** A single candidate is used as the output path. An optional `--reference DIR` matches loose files by both their filename identifier and exact stored/decompressed contents; a single such match is labelled `verified` and takes precedence over guesses. Entries with no candidates or several unverified candidates are kept as `_unknown/IDENTIFIER-INDEX.bin`; every candidate is retained in the manifest. Duplicate identifiers never cause files to be overwritten.

Scanning the TFX 2.05 executable helps recover more names. You can add known names in a UTF-8 file, one DOS path per line (blank lines and `#` comments are ignored):

```text
# Examples of known TFX resources
TUNES\INTRO.ADL
TUNES\INTRO.RLD
TUNES\INTRO.SCC
MISSIONS\MISS830.MIS
```

```sh
python3 did_unpack.py DID.DAT unpacked --scan TFX.DAT --names names.txt
```

Supply additional hint files with repeated `--scan` or `--names`, or additional loose-file roots with repeated `--reference`. Reference filenames are relative to that root, so point it at the directory containing `TFX.DAT`, not its parent. Filename inference is specific to TFX; other DID games may use different hashing. Use `--no-names` for those until their naming scheme has been validated.

## Other useful commands

```sh
# Inspect entries and candidate names without writing files.
python3 did_unpack.py DID.DAT --list --scan TFX.DAT

# Extract all decompressed resources under identifier-based names.
python3 did_unpack.py DID.DAT unpacked --no-names

# Preserve the exact stored payloads, including compression headers.
python3 did_unpack.py DID.DAT stored --raw --no-names
```

The default maximum decompressed size is 256 MiB per resource; change it with `--max-size BYTES` if required. Truncated streams, invalid matches and inconsistent archive indices produce an error. Unsupported RA versions are rejected. Other resource formats are preserved as stored; additional codecs are not claimed.

## Validation and scope

All resources in three CD TFX versions, two floppy installations and the December CD's Inferno demo were decoded and compared against the existing C RA implementation. See [validation](docs/validation.md) for exact results and [format notes](docs/format.md) for the reconstructed layout and hashing.

The tool does not convert extracted images, models, music or mission data into modern formats. It extracts their native resources for further analysis. Support for later EF2000/ADF/TAW archives and their filename algorithms is not claimed.

Run the synthetic regression tests with:

```sh
python3 -m unittest discover -s tests -v
```

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). The RA decoder derives from Benjamin Haisch's work; his attribution and source are recorded in the notice. This repository contains no game assets.
