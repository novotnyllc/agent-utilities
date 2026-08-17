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
