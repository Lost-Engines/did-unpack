# Credits and source provenance

The tool's original Python code is maintained by Lost Engines and distributed under GPL-3.0-or-later. Game archives and extracted assets are not part of this repository.

The RA version 2 decoder is a Python adaptation of Benjamin Haisch's **RA decompression class, version 1.0 (2006)**. His source permits its use freely provided he receives credit. The implementation reviewed for this work is the C adaptation included in QuickBMS:

https://github.com/LittleBigBug/QuickBMS/blob/master/src/compression/rage_xfs.c

Its original attribution is retained here:

```text
RA decompression class version 1.0
(c) 2006 Benjamin Haisch
email: john_doe@techie.com
You may use this code freely as long as you give me credit for it :)
```

This Python implementation adds explicit checks for truncation, tree bounds, invalid backreferences, declared output sizes and cyclic trees. Bitstream and raw-byte reads intentionally share one cursor.

TFX filename substitution and hashing were independently reconstructed from the September 1994 TFX 2.05 executable. The format notes identify the relevant routines and evidence.

Other useful prior research:

- [petitcoq's Inferno QuickBMS extraction script](https://reshax.com/topic/66-inferno-the-odyssey-continues-1994-ms-dos/) independently describes the same archive index layout.
- [Dragon UnPACKer's default driver](https://github.com/elbereth/DragonUnPACKer/blob/master/DragonUnPACKer/plugins/drivers/default/drv_default.dpr) has a structurally similar reader for later DID games, extracting resources under hash names. Its RA extraction code is disabled in the source examined.
- [Krishty's Sim Forums: DID.DAT research](https://simforums.krishty.com/viewtopic.php?t=311) discusses archive versions, missing names and RA compression in TFX/EF2000.

These sources informed our research and comparison. Neither the Inferno script nor Dragon UnPACKer's reader was copied into this implementation.
