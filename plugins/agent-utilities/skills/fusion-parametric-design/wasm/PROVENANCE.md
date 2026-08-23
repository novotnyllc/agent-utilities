# WASM asset provenance

## bgcode.wasm / bgcode.js

- **Upstream:** https://github.com/prusa3d/libbgcode
- **License:** AGPL-3.0-or-later (see THIRD_PARTY_NOTICES.md)
- **Build:** GitHub Actions workflow `build.yml`, job `build-wasm`, artifact `libbgcode-wasm`
- **Artifact run:** https://github.com/prusa3d/libbgcode/actions/runs/29907325752 (2026-08-21)
- **Artifact ID:** 8524439790
- **Commit at capture:** the `main` branch head as of 2026-08-21 (the repo does not tag releases; pin by artifact run ID above and check for newer runs before updating)
- **Contents:** `bgcode.js` (Emscripten JS loader, ~34 KB) + `bgcode.wasm` (~124 KB)
- **API used:** `bgcode2ascii_and_verify(ArrayBuffer) -> string` (checksum-verified binary-to-ASCII decode); also exports `ascii2bgcode` for encoding, not currently called

## How to check for updates

1. List recent successful `build-wasm` runs: `gh run list -R prusa3d/libbgcode -w build.yml`
2. Download the latest `libbgcode-wasm` artifact from a newer run than the ID recorded above
3. Diff the `.wasm` size; if it grew substantially, review the upstream changelog for API changes
4. Re-run the skill's test suite (the WASM tests exercise decode round-trip against a known fixture)
5. Update this file with the new run ID and date
