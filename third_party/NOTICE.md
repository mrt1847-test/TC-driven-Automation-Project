Third-party Notice
==================

This directory contains source vendored for TC Automation Studio runtime use.
Vendored source is checked into this repository so the product can run without
requiring a separate Webwright checkout. External Webwright paths remain
supported through settings and install scripts.

Each vendored project must keep its upstream license file in its source
directory. Project-level attribution, source version, and local patch notes are
kept here to avoid scattering product-specific notices across upstream files.

Microsoft Webwright
-------------------

- Vendored path: `third_party/webwright`
- Upstream: https://github.com/microsoft/Webwright
- Source commit: 734bc60ea73653498215694d0cc4bc96fbc09e9c
- License: MIT License, see `third_party/webwright/LICENSE`
- Copyright: Copyright (c) Microsoft Corporation.
- Version marker: `third_party/webwright/VENDORED_VERSION.txt`

TC Automation Studio is not an official Microsoft product and is not endorsed
by or affiliated with Microsoft. Webwright and Playwright names, logos, and
other marks remain the property of their respective owners.

Upstream citation requested by the Webwright README:

```bibtex
@misc{webwright2026,
  title        = {Webwright: A terminal is all you need for web agents},
  author       = {Lu, Yadong and Xu, Lingrui and Huang, Chao and Awadallah, Ahmed},
  year         = {2026},
  howpublished = {\url{https://github.com/microsoft/Webwright}},
  note         = {GitHub repository}
}
```

Local changes applied for this project:

- Windows native runs skip Webwright's bash-command text validator in
  `src/webwright/models/base.py`, matching the direction of
  microsoft/Webwright#30.
- Windows native workspace commands resolve Git Bash and execute commands with
  `bash.exe -lc` in `src/webwright/environments/local_workspace.py`.

Bundled Runtime Notices
-----------------------

`scripts/prepare-runtime.ps1` generates `runtime-staging/THIRD_PARTY_NOTICES.txt`
for Windows packaging. That generated notice includes this file, the bundled
Python license text when present in the embeddable Python directory, and a
metadata summary for installed Python packages such as Playwright, pytest, and
Webwright dependencies.
