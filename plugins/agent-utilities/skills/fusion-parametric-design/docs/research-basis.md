# Research basis

Accessed 2026-08-17.

## Nurb

- Skill source: https://github.com/Shpigford/nurb/blob/main/skills/nurb/SKILL.md
- Repository: https://github.com/Shpigford/nurb
- License: https://github.com/Shpigford/nurb/blob/main/LICENSE

The adaptation preserves workflow ideas rather than source code: research before design, measurement provenance, numerical inspection, reference meshes, assemblies, fit coupons, print-aware validation, visible iteration, and persistent handoff state.

## Official Autodesk Fusion MCP

- Overview: https://help.autodesk.com/view/fusion360/ENU/?guid=FMCP-OVERVIEW
- Connection: https://help.autodesk.com/view/fusion360/ENU/?guid=ADSKMCP_FusionDesktopMcp_connecting_to_the_fusion_mcp_server_html
- About Autodesk MCP servers: https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_CommonContent_about_autodesk_mcp_servers_html
- Autodesk article on live scripts/testing: https://www.autodesk.com/products/fusion-360/blog/build-your-own-fusion-add-ins-with-the-fusion-mcp/

Key architectural consequences:

- the desktop Fusion MCP is local and requires Fusion running;
- tools are dynamically discovered and may evolve;
- MCP servers execute explicit operations but are not autonomous workflow managers;
- the MCP can provide current API documentation, execute scripts, inspect errors, and support live test/refine loops;
- saves/checkpoints remain important before generated modifications.

## Official Fusion API references used by generated scripts

- User parameters: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/UserParameters.htm
- `UserParameters.add`: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/UserParameters_add.htm
- Parameter expressions: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/UserParameter_expression.htm
- Attributes: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Attributes.htm
- Parametric/direct design type: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Design_designType.htm
- Components/occurrences: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Occurrences_addNewComponent.htm
- Root-context occurrence collection and paths: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Component_allOccurrences.htm and https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Occurrence_fullPathName.htm
- Root-context B-Rep body proxies: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Occurrence_bRepBodies.htm
- `Compute All`: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Design_computeAll.htm
- Timeline health: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/TimelineObject_healthState.htm
- Minimum distance: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/MeasureManager_measureMinimumDistance.htm
- Interference: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Design_analyzeInterference.htm
- Precise B-Rep-only occurrence bounds: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Occurrence_preciseBoundingBox.htm
- All-geometry bounds: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Occurrence_boundingBox2.htm and https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BoundingBoxEntityTypes.htm
- Solid/volume validation: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BRepBody_isSolid.htm and https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BRepBody_volume.htm
- Export manager: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ExportManager.htm
- Mesh import: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/MeshBodies.htm
- July 2026 API additions including mesh comparison: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WhatsNew.htm

## Enclosure feature toolkit: plastic-feature, entitlement, and manufacturer findings (2026-08-21 design pass)

### Autodesk plastic features and the entitlement boundary

- **Boss.** Autodesk documents Boss as a Design Extension UI feature and a
  complete public API exists (`Features.bossFeatures`,
  `BossFeatures.createInput/add`, `BossFeatureInput`, `BossFeature`).
  Public API existence does **not** establish that an unentitled base account
  can call it — runtime entitlement is unresolved and requires a two-license
  live probe. The toolkit's boss recipes do not depend on `BossFeatures`
  either way.
- **Snap Fit, Lip, Rest.** Documented as Design Extension UI commands; the
  public API documentation searched during the design pass established no
  specialized creation collections analogous to `BossFeatures`. Absence of
  documentation is not proof of runtime absence, so current-build probes are
  the open question — but until one is demonstrated, specialized creation is
  treated as unavailable and base recipes own the geometry.
- **Plastic Rules.** Extension-owned, injection-oriented (`Design.designPlasticRules`,
  `PlasticRules.addByCopy`). Intentionally **not** depended upon in any form;
  their semantics do not carry the FDM evidence model the toolkit requires.

These findings are recorded as named Autodesk sources per the design text
(Fusion Help product documentation for Plastic > Create > Boss / Lip / Rest /
Snap Fit / Plastic Rules, and the Fusion API reference for the Boss and
PlasticRules members); no URLs beyond the official references above are
invented here.

### Manufacturer and FDM sources used as evidence classes

The design's rule model cites these named sources as the *class* of evidence
each parameter family requires — fixture-specific values are valid only for
the product they name, never as universal defaults:

- **SPIROL insert guidance** — heat-set/threaded-insert recommended hole,
  wall, and insertion-depth practice; class `manufacturer-specified`. The
  published Series 29 M3 example dimensions are valid for that product only.
- **Covestro snap-fit plastics design guide** — cantilever/ring snap strain
  and geometry guidance; class `material-datasheet`/manufacturer design guide.
- **BASF snap-fit calculation tooling** — material-and-geometry-dependent snap
  estimates with explicit validation caveats; same evidence class, reinforcing
  that no universal snap number ships.
- **Parker O-Ring Handbook** — O-ring gland/cross-section design for static
  and dynamic seals; class `standard`/`manufacturer-specified`. No generic
  gland default is shipped.
- **Prusa FFF design guidance (official)** — printed fit/tolerance depends on
  machine setup, orientation, and material; extrusion width, overhang, and
  layer orientation drive printable results. Supports the closed list of
  forbidden unsourced numbers in
  `references/enclosure-feature-rules.md`.

No third-party source code was reused from any of these sources; they inform
evidence classification and refusal policy only.
