# Validation

Validation performed 13 October 2026 against the local archival collection. No retail assets are included in this repository.

## Complete archive comparison

All resources were decoded with the Python implementation. Every RA resource was also decoded with the C implementation in QuickBMS (`src/compression/rage_xfs.c`, by Benjamin Haisch), and the outputs were compared byte-for-byte. The C source SHA-256 was `0ba896e38a18909dcff7932dfe147a30974bbfc5ee29a014efabce17a185b1d0`.

| Archive | Entries | RA resources | Total decoded bytes | Mismatches |
|---|---:|---:|---:|---:|
| installs/cd_1993_12/TFX/DID.DAT | 3,474 | 2,390 | 21,805,861 | 0 |
| installs/cd_1994_03/TFX/DID.DAT | 3,148 | 2,294 | 24,895,619 | 0 |
| installs/cd_1994_09/TFX/DID.DAT | 3,488 | 2,416 | 24,975,181 | 0 |
| installs/floppy_1993_11_loose/TFX/DID.DAT | 3,460 | 2,381 | 23,421,008 | 0 |
| installs/floppy_1994_03_archived/TFX/DID.DAT | 3,460 | 2,381 | 23,421,008 | 0 |
| extracted/cd_1993_12/files/INFERNO/DID.DAT | 60 | 4 | 11,389,986 | 0 |

That is **17,090 entries and 11,866 RA resources**, with zero mismatches. Raw entries are emitted unchanged. Matching the existing decoder validates the port against that reference; it does not independently prove every native resource format or the correctness of every recovered filename.

Archive SHA-256 values:

- `installs/cd_1993_12/TFX/DID.DAT`: `4ec6b35627b12dfe41b9da59d09816fdf105aebb61d662c80553b8241c85b085`
- `installs/cd_1994_03/TFX/DID.DAT`: `e534c24868c45009f045232619a067f44f8a6d7019af44692dcc6c9872d9a2dd`
- `installs/cd_1994_09/TFX/DID.DAT`: `e62a4b372a9a4b2d4c881a4ea6ec6b132e8db62f83d5f7e45ba05b772ffbee40`
- `installs/floppy_1993_11_loose/TFX/DID.DAT`: `905f7df315cd85a4bee5f352baf41a08adf4f0a6b822b3c28a28b55b04df0334`
- `installs/floppy_1994_03_archived/TFX/DID.DAT`: `2e009df436d27d05ae749ce72e574a1e3af9b39ca202c3feb7cdc5e8eaf65d07`
- `extracted/cd_1993_12/files/INFERNO/DID.DAT`: `9c267607bb720e7f020a94c1666d479ea34c7cd572ece1e411c539da18dd8e84`

## Filename recovery

The September 1994 TFX 2.05 archive, scanned together with its installed TFX.DAT executable and no supplied name list, produces:

- 2,060 entries with a single candidate filename.
- 175 entries with competing candidates, retained under identifier-based names.
- 1,253 entries without a candidate, also retained under identifier-based names.

The music identifiers and the separately installed MISS830.MIS were verified against matching loose payloads across the TFX copies. A known Mig-29 model identifier exercises the underscore-specific hash behavior. The rest of the single-candidate names remain recovery hypotheses, explicitly recorded as such. A reference-directory check identifies six loose files (the three intro music files, MISS830.MIS and both COL placeholders) by identifier plus exact content; this resolves two misleading automatic music-name guesses without discarding the competing candidates.

## Synthetic regression tests

The asset-free unittest suite covers an RA literal fixture, truncation, output size limits, wrong versions, archive offsets and name-table boundaries, TFX hashing, path safety, duplicate identifiers, ambiguity handling, raw extraction, output refusal and command-line diagnostics. The tiny RA fixture was also verified against the C reference.

Run `python3 -m unittest discover -s tests -v` from the repository root.
