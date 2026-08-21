# Fusion data placement and the shared component catalog

Where a design lives and where its parts come from are decided before geometry.
Both decisions are Fusion-native: hubs, projects, folders, design files, and
linked components are the mechanism, never a host-side registry.

## The data-placement gate

Before modeling, determine and record:

| Question | Default answer |
|---|---|
| Which Hub? | The hub the user's team already works in; ask when more than one is active. |
| Existing project or new? | Repository/product identity is a strong default: work belonging to an existing product goes in that product's project. A new project marks a distinct ownership, permissions, or lifecycle boundary — not a new part. |
| New design file or existing? | A new deliverable is a new design file with a human-sensible name. Edits to an existing product open its recorded document by dataFile id. |
| Internal or external component? | Internal components for assembly-specific geometry designed and released together (a base and cover of one enclosure). Separate design files, inserted as linked external components, for anything independently reusable or independently versioned. |
| Catalog placement? | Every cross-product reusable part lives in the shared component catalog project and is linked in, never copied. |

Ask one concise question when placement is genuinely ambiguous; otherwise
decide, state the decision, and proceed. Production modeling never begins in an
arbitrary or unsaved `Untitled` document — see the document naming and identity
rules in `references/design-doctrine.md` § Document lifecycle.

## Purchased-part CAD resolution

Before manually modeling any real purchased component:

1. **Identify** the manufacturer and exact part number, revision, and variant.
2. **Check Fusion's native part sources**: Insert Fastener for standard screws,
   nuts, and washers; Manufacturer Parts; supplier and catalog integrations
   such as McMaster-Carr; existing shared Fusion components. Standard catalog
   hardware is never manually generated unless the native/catalog part is
   unavailable or incorrect.
3. **Search external CAD** in credibility order: the manufacturer's official
   CAD downloads; authorized distributor CAD; established CAD libraries;
   community models as provisional sources only.
4. **Import once** into the part's canonical Fusion component file — STEP, SAT,
   Parasolid, or native format — and **check it in Fusion**: Measure and
   Properties against the datasheet and the user's caliper measurements. The
   owned physical part resolves conflicts.
5. **Record provenance and confidence** on the canonical component: source,
   part number, revision, and whether the geometry is official, verified
   third-party, or provisional.
6. **Model manually only as the last resort**, once, in the canonical file —
   never as an anonymous project-specific box inside a product assembly.

## Fitness for purpose decides the fidelity

The resolution ladder is proportionate, never absolute. When the task needs
only occupancy, clearance, or arrangement — an enclosure around parts is the
canonical case — a simple box or cylinder at the right dimensions is a
legitimate component, not a failure to source. It gets a sensible name
("Fuse Holder Envelope"), is marked provisional in its description or
attributes (base-tier metadata, per the extension rule below), and is revised
or replaced with real CAD later without ceremony, when and if the task needs
real geometry. Refinement is on demand, never preemptive.

Dimension sources for such geometry, in rough order of trust: user-supplied
measurements and calipers > datasheet > credible CAD model > product listing
dimensions > visual estimation. Marketplace listing dimensions are frequently
wrong — usable as a starting point, not gospel. A photo of the part, or the
part visible next to anything of known scale, supports a stated, revisable
estimate, and making that estimate is an expert move rather than a shortcut.

The sourcing decision is quick: a short search for real CAD, then either an
import or a provisional box, and back to modeling. The ladder never delays the
visible-result loop.

## The shared component catalog

Canonical purchased-part components live in a shared Fusion component project
(one per hub, organized by category folders — fasteners, connectors,
electronics modules, terminal blocks), and:

- have clear names carrying the manufacturer and part number ("WAGO 221-413",
  "Silver 24T12-2A Converter");
- carry part number, description, and manufacturer in the component properties
  so BOM and parts-list exports stay correct;
- preserve official imported geometry when available, with the import as the
  base and any authoring datums added on top;
- are checked against datasheets and physical measurements, with provisional
  models marked as such until verified;
- are inserted into assemblies as **linked external components**, with multiple
  occurrences for quantity — two WAGOs are two occurrences of one canonical
  WAGO component, never two copies;
- use Configurations for genuine part families and variants (lengths of one
  screw line, pole counts of one terminal block), not for unrelated parts;
- are updated in place: a corrected canonical part flows to every consuming
  assembly through Fusion's linked-design version updates, and consumers choose
  when to accept the update.

Use Derive and Insert Derive when a product needs a controlled subset of a
canonical design rather than the whole component. Do not reproduce component
catalogs, product structures, version relationships, or part identity in
host-side code when Fusion can own them.

None of this requires a paid extension. The Manage extension owns item
management and managed BOM machinery, and the expected common case is that the
user does not have it: part numbers and part identity live in base Fusion's
component properties, description fields, attributes, and names, and the
linked-component catalog with recorded provenance is the base-tier BOM. Do not
build a catalog workflow that assumes the Manage extension; if managed items
would genuinely transform the user's process, mention the extension once,
briefly, and proceed with the base-Fusion path.

## Placement of the parts inside an assembly

Purchased parts are positioned and related through Fusion component and
assembly tools — joints, as-built joints, joint origins, rigid groups,
grounding, component origins — never through custom coordinate code. Grounded
components anchor the stack; joints express the real assembly relationships;
Contact Sets and Motion Links apply only when actual motion or contact requires
them.

## When a manifest exists

In the automation lanes, the manifest's `references` entries record each
purchased part's source identity, locator, revision, and confidence, and the
packing ledger records installed transforms. The catalog remains the geometry
authority; the manifest records the evidence trail around it.
