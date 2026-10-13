# Footer-indexed DID archive format

This describes the archives examined in TFX and the bundled Inferno demo. It is not a universal specification for every later DID game.

## Container

All integers are little-endian. At offset zero, a `uint32` points to the index. Resource payloads occupy the bytes between this pointer and the index; each entry independently describes a stored slice.

The index begins with four `uint16` values:

| Field | Meaning |
|---|---|
| Entry count | Number of 12-byte resource records |
| Directory count | Number of directory-prefix strings |
| Extension count | Number of extension strings |
| Name-table byte size | Combined size of both string tables, including length bytes |

Each string is a one-byte length followed by that many ASCII bytes. Directory prefixes precede extensions. The strings are followed by resource records:

| Bytes | Meaning |
|---|---|
| 4 | Filename identifier/hash |
| 4 | Absolute payload offset |
| 4 | Stored payload size |

Some archives have additional bytes after the records. For example, the two floppy copies examined have different four-byte trailers while their preceding resource data is identical. The meaning of that trailer is unresolved; the manifest preserves its exact bytes.

The tool validates name-table boundaries and payload bounds. It does not rely on entries having a particular hash ordering, or reject duplicate identifiers. Entries retain their original index and duplicates receive distinct output paths.

## RA version 2

Resources beginning with `52 41 00 02` (`RA`, version 2) have a 12-byte header. Bytes 4–7 contain the uncompressed size as a `uint32`. The remaining four header bytes are not interpreted by this tool; they are preserved in raw extraction. No header-checksum validation is claimed.

The compression uses literal runs and overlapping backward matches, with three binary decoding tables for counts, lengths and offsets. Bits are read most-significant first. Raw bytes and bit-buffer refills advance a shared input cursor; a raw read does not discard remaining buffered bits. That interleaving matters.

The decoder consumes one leading bit, then reads blocks with a raw little-endian command count. Each block supplies its decoding tables, followed by commands containing a literal run and optional match. A final bit selects another block or terminates the stream. Output size must equal the declared size.

The Python decoder follows Benjamin Haisch's published implementation; see [credits](../NOTICE.md). It additionally rejects malformed trees, invalid backward references and output overruns instead of reading outside buffers.

## TFX filename lookup

The archive does not directly associate each entry with a directory or extension index. Its whole identifier is the hash of a substituted filename. Treating bits of the identifier as directory/extension fields would be incorrect.

TFX first lowercases the DOS path, then:

1. Finds the first matching directory prefix in the archive's table. It replaces that prefix with one character: ASCII `0` plus the zero-based directory index.
2. Finds the first dot. If the extension from that dot matches an extension-table entry, it replaces the extension with ASCII `A` plus its zero-based index. If the extension is unknown, it removes only the dot.
3. Hashes the resulting string. Generated table-code characters retain their case.

In the September 1994 archive, `tunes\` is directory 20 and `.adl` is extension 33, so `tunes\intro.adl` becomes `Dintrob`, producing `0x72de1438`. `.rld` and `.scc` become `Dintroc` and `Dintroe`, producing `0x73df1538` and `0x75e11338`. The identifiers were verified independently by matching the separately installed music payloads to the archive.

The hash accumulates four byte-sized values:

- Sum of non-underscore character values.
- Sum of successive cumulative sums.
- A value shifted left once and XORed with each non-underscore character; an underscore instead subtracts its character position.
- A shifting record of whether each character is greater than its predecessor; a preceding underscore skips that comparison.

Byte arithmetic wraps modulo 256. The final word contains length modulo 16 in bits 28–31, character sum modulo 16 in bits 24–27, cumulative sums in bits 16–23, shifted XOR in bits 8–15, and rising comparisons in bits 0–7.

### Executable evidence

These file offsets apply only to the 1,032,503-byte September 1994 `TFX.DAT`, SHA-256 `2cc41a39fa95a2c9fd883c4220d7bdd9cca00c543c89b019eb270763f59d1d9a`:

- Archive lookup/substitution routine: `0xc8af0`.
- Hash routine: `0xd6484`.
- Signed binary search of identifiers: `0xc889c`.
- Index-loading routine: `0xc8948`.

The executable embeds a DOS extender and an LE image. Raw disassembly offsets are not the same as object-relative runtime addresses. The LE header is at `0x35304`; its enclosing MZ header is at `0x352a4`.

## Filename recovery and collisions

The tool gathers explicit file references and short terminated identifiers from decompressed resources and optional scanned files. It tries those stems with archive directory/extension codes and compares the resulting identifiers against the index. Supplied lists provide additional candidates.

This hash is not collision-free. A unique candidate among the strings available to the tool is still a hypothesis; the original name might be absent. The manifest labels such names `candidate`. Multiple matches are labelled `ambiguous` and retained under identifier-based paths. `--reference` verifies names against a known loose copy by identifier and exact stored/decompressed content. A single verified name takes precedence, while all competing guesses remain in the manifest. Name validation by game lookup or native format can also strengthen confidence.

Hashing for later EF2000/ADF/TAW builds may differ. Successfully reading their structurally similar archive index does not establish correct filename recovery. Use `--no-names` when examining unvalidated naming schemes.
