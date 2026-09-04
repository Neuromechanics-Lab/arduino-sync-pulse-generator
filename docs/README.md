# PRE-Sync documentation

| Document | Contents | Source of truth |
|---|---|---|
| [DATASHEET.md](DATASHEET.md) | Specifications, ratings, failure behaviour | hand-written |
| [INTERFACE.md](INTERFACE.md) | Pinout, signal levels, serial commands | **generated** from firmware |
| [BOM.csv](BOM.csv) | Bill of materials | hand-maintained |
| [wiring/](wiring/) | Panel harness diagram | **generated** from `presync-harness.yml` |
| [TEST_PROCEDURE.md](TEST_PROCEDURE.md) | Acceptance tests for a built unit | hand-written |
| [api/](api/) | Python analysis toolkit reference | **generated** from docstrings |

## Regenerating

Three documents are generated and must not be edited by hand — an edit is
lost the next time they are rebuilt, and the source is the authority:

```sh
python3 tools/gen_interface_doc.py   # docs/INTERFACE.md
tools/gen_wiring.sh                  # docs/wiring/*.png,svg,html
tools/gen_api_docs.sh                # docs/api/
```

The last two need a virtual environment and graphviz:

```sh
brew install graphviz
python3 -m venv .venv-docs
.venv-docs/bin/pip install wireviz pdoc numpy scipy pyxdf matplotlib
```

## Checking the BOM

```sh
python3 tools/check_bom.py
```

Reports which lines still lack a manufacturer part number, supplier or price.
The BOM is incomplete until this runs clean; **do not fill it with estimates**,
since a fabricated price is worse than a visible blank.

## What is still missing

Measurements only a built unit can provide, tracked in
[TEST_PROCEDURE.md](TEST_PROCEDURE.md): rise/fall times, channel-to-channel
skew, generator clock accuracy in ppm, and demonstration of the independent
driver claim. These appear as *TBM* in the datasheet.
