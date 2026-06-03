# Third-Party Legal And Attribution

Last reviewed: 2026-06-03

This document summarizes how TC Automation Studio complies with vendored and bundled
open-source components. It is engineering guidance, not legal advice. Confirm with your
legal team before commercial redistribution.

## Vendored Microsoft Webwright

| Item | Value |
|------|--------|
| Path in repo | `third_party/webwright/` |
| Upstream | https://github.com/microsoft/Webwright |
| Commit | `734bc60ea73653498215694d0cc4bc96fbc09e9c` (see `VENDORED_VERSION.txt`) |
| License | MIT — full text in `third_party/webwright/LICENSE` |
| Copyright | Copyright (c) Microsoft Corporation |

MIT permits use, modification, and redistribution when the copyright notice and
permission notice are included in copies or substantial portions of the software.

Local patches for Windows native execution are documented in
[third_party/NOTICE.md](../third_party/NOTICE.md).

### Product disclaimer

TC Automation Studio is not an official Microsoft product and is not endorsed by
Microsoft. **Webwright** (the agent harness) and **Playwright** (browser automation)
are different projects; do not imply official affiliation in marketing or UI copy.

### Academic citation

If you publish research that builds on Webwright, cite the repository as described in
`third_party/NOTICE.md` and the upstream README.

## Bundled Windows runtime (`dist:win:full`)

`npm run prepare-runtime` writes `runtime-staging/THIRD_PARTY_NOTICES.txt`, which includes:

1. `third_party/NOTICE.md`
2. Microsoft Webwright MIT license full text (from vendored `LICENSE`)
3. Bundled Python license text when `python/LICENSE.txt` exists in the embeddable layout
4. Installed Python package license metadata (pip `importlib.metadata`)
5. A note that Playwright browser binaries under `ms-playwright/` carry their own notices

Electron packages `runtime-staging` as `resources/runtime/` (see `apps/desktop/electron-builder.json`).
End users should receive `THIRD_PARTY_NOTICES.txt` inside the installed app resources.

## Other components (not vendored as source)

| Component | How it is used | Typical license | Notice location |
|-----------|----------------|-----------------|-----------------|
| Playwright (Python) | pip + browser install in bundled Python | Apache 2.0 | pip metadata in `THIRD_PARTY_NOTICES.txt`; browser notices under `ms-playwright/` |
| Embeddable Python | Windows embed zip from python.org | PSF License | `LICENSE.txt` in staged `python/` when present |
| Electron / Node deps | desktop build | Various | Electron app `LICENSE` files in `node_modules` at build time; aggregate for release builds as needed |
| FastAPI worker deps | `apps/worker/requirements.txt` | Various | pip metadata in bundled notices when staged |

## Repository checks

Run before release packaging:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate-third-party.ps1
```

Live runtime staging also asserts `LICENSE` and `VENDORED_VERSION.txt` on the Webwright
source tree before copy.

## Maintainer checklist

- [ ] `third_party/webwright/LICENSE` unchanged from upstream MIT text
- [ ] `VENDORED_VERSION.txt` matches the vendored commit
- [ ] Local patches listed in `third_party/NOTICE.md`
- [ ] `scripts/validate-third-party.ps1` passes
- [ ] `npm run prepare-runtime` produces `runtime-staging/THIRD_PARTY_NOTICES.txt`
- [ ] Installed `resources/runtime/THIRD_PARTY_NOTICES.txt` opens from Settings (packaged app)
- [ ] No use of upstream `webwright_logo.svg` as the Studio product icon without separate approval

## Related documents

- [third_party/NOTICE.md](../third_party/NOTICE.md)
- [RUNTIME_SPEC.md](./RUNTIME_SPEC.md) — bundling contract
- [README.md](../README.md) — short third-party pointer
