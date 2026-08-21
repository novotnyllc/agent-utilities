# Design State

Use one copy per Fusion design. Replace the instructional text with project facts; do not mark an unperformed check as passed.

## Intent and current variant

- Project intent: Not recorded.
- Intended user/environment: Not recorded.
- Active configuration or parameter set: Default.
- Current release state: Exploratory.
- Known scope exclusions: None recorded.

## Fusion document state

- Fusion document: Not recorded.
- Document dataFile id (durable identity; from the document-save report — later sessions reconnect by this id, never by name): Not recorded.
- Document project id / folder id: Not recorded.
- Document/version/checkpoint: Not recorded.
- Fusion release: Not recorded.
- Fusion MCP/package version: Not recorded.
- Design type: Must be parametric before managed mutation.
- Manifest SHA-256: Not recorded.
- Latest inventory report: Not recorded.
- Latest verification report: Not recorded.

## Source and parameter ledger

| Parameter | Expression | Role | Source id/revision | Confidence | Provisional | Notes |
|---|---:|---|---|---|---|---|
| None recorded | — | — | — | — | — | — |

Unresolved critical dimensions: None recorded.

## Mesh sources and reconstruction

| Mesh source id | File sha256 | Units (source) | Provenance | B-Rep source preferred? | Recorded path | Rationale |
|---|---|---|---|---|---|---|
| None recorded | — | — | — | — | — | — |

Bound Fusion bodies (component path / body name, from the capture report): None recorded.

Deviation verdict — record both directions and the question each answers; never one combined number:

| Direction | Question it answers | Declared threshold (mm) | Result | Severity |
|---|---|---:|---|---|
| Reconstruction → source | Did the rebuild stay on the scan? | — | Not run | — |
| Source → reconstruction | Did the rebuild capture what was scanned? | — | Not run | — |

Threshold rationale: Not recorded. Fusion version and preview APIs used: Not recorded.

Parametric rebuild — record the coverage label and its fraction together; the
label on its own is not the result:

| Field | Value |
|---|---|
| Coverage label (`parametric-full` / `parametric-partial` / `reconstruction-refused`) | Not run |
| Delivered area fraction | — |
| Program sha256 / dump sha256 | — / — |
| Rebuild nonce / editability nonce | — / — |
| Archetypes built (kind × count) | — |
| Fillets skipped, with reason | None recorded |
| Parameters in `checked` | None recorded |
| Parameters `not_exercised` | None recorded |
| `interactions_exercised` | `false` — the loop perturbs one parameter at a time |

Unreconstructed regions — every one, with the gate that stopped it. A partial
reconstruction is a success, and this is the half of it that must not go
missing:

| Region / archetype id | Area fraction | Gate |
|---|---:|---|
| None recorded | — | — |

## Packing and component ledger

| Item | Installed transform/orientation | Authoring (reference) model | Packing (checking) model | Keep-out volumes | Support/retention | Insertion/removal sequence | Confidence |
|---|---|---|---|---|---|---|---|
| None recorded | — | — | — | — | — | — | — |

Smallest recorded critical packing margin: Not measured.

## Verification results

| Check | Required result | Actual result | Status | Evidence |
|---|---|---|---|---|
| Parametric design | Parametric | Not checked | not run | — |
| Compute All | Completes | Not checked | not run | — |
| Timeline health | No unexplained warning/error | Not checked | not run | — |
| Required components | Present once at declared paths | Not checked | not run | — |
| Expected print parts | Positive-volume solids | Not checked | not run | — |
| Clearance checks | At or above manifest minimums | Not checked | not run | — |
| Forbidden interference | Zero | Not checked | not run | — |
| Parametric range/configurations | All intended cases recompute and verify | Not checked | not run | — |
| Printability review | Applicable checks documented | Not checked | not run | — |

Required visual evidence:

- Exterior view: Not captured.
- Internal packing view: Not captured.
- Section or transparent view: Not captured.
- Open/service state: Not captured or not applicable.

## Physical validation

Use only `not run`, `pass`, `fail`, or `not applicable`.

| Test | Status | Article/revision | Conditions | Result/evidence |
|---|---|---|---|---|
| Actual component fit | not run | — | — | — |
| Connector/cable fit | not run | — | — | — |
| Fit coupon | not run | — | — | — |
| Fastener torque/retention | not run | — | — | — |
| Lid/clip cycles | not run | — | — | — |
| Thermal soak | not run | — | — | — |
| Proof load | not run | — | — | — |
| Comfort/attachment | not run | — | — | — |
| Ingress claim | not run | — | — | — |

## Manufacturing assumptions

Material decision — copy from the manifest's `material_decision`; a family with no named formulation is a legitimate row, a guessed formulation is not.

| Chosen material | Family | Formulation | Source id | Confidence | Coupon | Printer requirements | Unresolved risk |
|---|---|---|---|---|---|---|---|
| Not decided | — | — | — | — | — | — | Material not chosen; no material-dependent geometry may be finalized. |

- Process/material: Not recorded.
- Printer/nozzle/layer height: Not recorded.
- Intended build orientation: Not recorded.
- Slicer and exact machine/material/process profile: Not recorded.
- Support strategy: Not recorded.
- Known anisotropic load direction: Not recorded.
- Thermal/material limits: Not recorded.

## Exports

| Artifact | Fusion version/checkpoint | Component path | Units | Export options | Byte size | File SHA-256 | Export run ID | Verification report | Slicer/profile | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| None | — | — | — | — | — | — | — | — | — | — |

Rows come from the export transaction's `design_state_rows`; append them verbatim rather than hand-copying hashes.

## Unsupported or outstanding proof

- No outstanding items recorded. Replace this line with every unsupported digital check, provisional measurement, required external analysis, and unperformed physical test.

## Rejected decisions

| Decision rejected | Reason | Evidence | Reconsider only when |
|---|---|---|---|
| None recorded | — | — | — |
