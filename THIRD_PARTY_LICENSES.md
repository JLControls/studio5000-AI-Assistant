# Third-Party Notices

## `src/acd`

The vendored `src/acd` package is derived from the Apache-licensed
[`hutcheb/acd`](https://github.com/hutcheb/acd) project.

- Fork commit: `038d120d9f568aa371a7f029c4f740f20fad7276`
- Original license: Apache License 2.0
- License text: [`third_party/acd/LICENSE`](third_party/acd/LICENSE)
- Local v38 patches: `acd/l5x/elements.py`, `acd/l5x/export_l5x.py`, and
  `acd/record/comments.py`

The package is vendored so the MCP’s offline ACD-to-L5X conversion does not
depend on a separate checkout or an editable installation.
