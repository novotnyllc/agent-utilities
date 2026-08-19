# Mesh reconstruction

## What conversion does and does not recover

Mesh-to-B-Rep conversion recovers a shape. It recovers no sketches, no constraints, no dimensions, and no feature history. A cylinder comes back as a many-sided prism with no circular edge to select; a fillet comes back as thousands of facets. `ParametricFeatureMeshConvertOperationType` only means the convert operation re-runs when the mesh changes — it does not restore parameters.

A converted body is **faceted**, never parametric, and must never be reported as parametric.

## Capture before anything

Before any edit, record the source in `mesh_sources`:

- `sha256` of the file bytes. A moved or edited file fails closed on the hash; it is never silently re-measured.
- `units` with `unit_source` — `declared`, `file`, or `guess`. An STL carries no unit, so a 1000x scale error validates clean. A `guess` must name the heuristic and the threshold that produced it, and that reason is printed with every capture report.
- `provenance` — `designed_export` or `capture`. **No mesh statistic distinguishes them**: a designed model scores like a scan on every computable measure. It is a declared input, and it governs confidence — fitted values from a capture stay provisional until a coupon proves them.
- `alignment_transform`, the applied coordinate-frame evidence. Record the identity when nothing was moved.
- `brep_source` when a STEP or other B-Rep exists. Prefer it, and record that it does not restore design intent and may not match the mesh people actually printed.

The source mesh body is never modified, converted in place, or overwritten. The capture transaction is read-only: it reports triangle count, `isClosed`, `isOriented`, volume, the oriented minimum bounding box, and the Fusion version, and it creates nothing. Every mesh API it touches is preview; a value it could not read is reported absent, never guessed.

## Choose the path, then record it

Classification happens **before** any geometry operation, and downstream entry points refuse to run without the record. Exactly one path:

| Situation | Path |
| --- | --- |
| Local or cosmetic edit; the object is a fixture to clear rather than a design to change; clearance-only use | `mesh-edit` |
| Watertight, low-facet mechanical part needing a boolean, below a **declared** facet budget | `faceted-brep` |
| Dimensional or structural change; or a boolean on a mesh that is not watertight or is over budget | `parametric-rebuild` |

Facet ceilings are declared per request, never a module constant: the widely-cited 10k/50k numbers are unverified and version-specific, and Fusion's own `errorOrWarningMessage`/`healthState` are the authority at conversion time.

Both mature commercial tools expose three separate commands and make the human choose. What is automated here is the *recording and enforcement* of the choice, not the choice itself.

## Path notes

- **`mesh-edit`** — keep the body a mesh, use Fusion's mesh tools, and never claim a parametric result. Clearance and interference claims still require a native positive-volume B-Rep envelope, never a mesh-only occurrence.
- **`faceted-brep`** — convert only after the named refusal ladder, and label the result faceted. "Converted successfully into 9,000 unselectable facets" is a poor outcome, not a success.
- **`parametric-rebuild`** — rebuild only the geometry the edit requires, from datums and sections extracted from the immutable source. This is not a whole-part auto-converter. Near-coaxial, near-perpendicular, near-symmetric, and near-nominal values are surfaced as proposals carrying their deviation, never snapped silently.

## Honesty rules

- The handoff distinguishes mesh cleanup, faceted conversion, and true parametric reconstruction. The second is never reported as the third.
- A fit coupon is required before any claim of physical mating.
- A missing preview API fails closed with a clear message rather than degrading silently.
