# Enclosure feature capability matrix

Final capability classification for the base-Fusion enclosure feature toolkit,
transcribed from the implementation-ready design specification. Every row
receives exactly one requested capability classification.

Legend:

```text
G = geometric equivalence: H high, M medium, N none/not applicable
P = parametric equivalence: H high, M medium, N none
N = native-feature equivalence: Y yes, N no, O optional/unresolved native extension path
Evidence:
  HW = hardware/manufacturer/standard data
  MAT = material/formulation evidence
  FAB = fabrication/coupon evidence
  USER = explicit design choice
Physical:
  Y = required before functional claim
  C = coupon strongly/conditionally required
  N = geometry does not inherently require physical proof
```

| Capability | Classification | G/P/N | Public base-Fusion approach | License | Owner | Evidence | Physical | Work package | Important limitation |
|---|---|---|---|---|---|---|---|---|---|
| Single-body support boss | `supported-recipe` | H/H/N | Sketch + Extrude + Combine | base | `boss` | USER/FAB | C | Boss/hardware | not Autodesk BossFeature |
| Coordinated base/lid boss pair | `supported-recipe` | H/H/N | shared datum + two explicit boss sides | base | `boss` | HW/FAB | C | Boss/hardware | assembly context required |
| Through-hole screw boss | `supported-recipe` | H/H/N | boss + Hole/cut | base | `boss` | HW | C | Boss/hardware | hardware dimensions sourced |
| Clearance-hole boss | `supported-recipe` | H/H/N | Hole clearance API where available | base | `boss` | HW/FAB | C | Boss/hardware | modern Hole API version gate |
| Counterbored socket-head seat | `supported-shared-primitive` | H/H/N | Hole/cylindrical seat cut | base | `holes_threads` | HW | C | Boss/hardware | selected fastener governs seat |
| Countersunk flat-head seat | `supported-shared-primitive` | H/H/N | Hole or conical/revolved seat | base | `holes_threads` | HW | C | Boss/hardware | angle/head dimensions sourced |
| Spot-faced angled/curved seat | `supported-shared-primitive` | H/H/N | axis-normal datum + shallow cut | base | `holes_threads` | HW | C | Boss/hardware | explicit screw axis required |
| Heat-set-insert boss | `supported-recipe` | H/H/N | boss + insert pocket | base | `boss` | HW/FAB | Y | Boss/hardware | insert-specific, coupon-sensitive |
| Captive square-nut boss | `supported-recipe` | H/H/N | square pocket + optional slot | base | `boss` | HW/FAB | C | Boss/hardware | process clearance not geometric |
| Captive hex-nut boss | `supported-recipe` | H/H/N | hex pocket + optional slot | base | `boss` | HW/FAB | C | Boss/hardware | process clearance not geometric |
| Self-tapping screw boss | `supported-recipe` | H/H/N | boss + sourced pilot | base | `boss` | HW/MAT | Y | Boss/hardware | no universal pilot diameter |
| Thread-forming screw boss | `supported-recipe` | H/H/N | boss + sourced pilot | base | `boss` | HW/MAT | Y | Boss/hardware | manufacturer pilot required |
| Native tapped boss | `supported-recipe` | H/H/N | Hole tapped API / ThreadFeature | base | `boss` | HW | C | Boss/hardware | version-aware Hole path |
| Modeled-thread boss | `supported-recipe` | H/H/N | native modeled ThreadFeature | base | `boss` | HW/FAB | C | Boss/hardware | print fidelity still unproven |
| PCB mounting standoff | `supported-recipe` | H/H/N | boss tied to PCB datum | base | `boss` | HW/USER | C | Boss/hardware | PCB datum must be explicit |
| Blind boss | `supported-recipe` | H/H/N | finite boss + finite bore | base | `boss` | USER/HW | C | Boss/hardware | none beyond source dimensions |
| Open-ended boss | `supported-recipe` | H/H/N | through/open bore | base | `boss` | USER/HW | C | Boss/hardware | none |
| Ribbed boss | `supported-recipe` | H/H/N | boss + reinforcement primitive | base | `boss` | MAT/FAB | Y for load claim | Boss/hardware | not structural validation |
| Gusseted boss | `supported-recipe` | H/H/N | boss + gusset primitive | base | `boss` | MAT/FAB | Y for load claim | Boss/hardware | same |
| Wall-connected boss | `supported-recipe` | H/H/N | explicit boss-wall reinforcement | base | `boss` | MAT/USER | Y for load claim | Boss/hardware | explicit wall required |
| Planar-surface boss | `supported-recipe` | H/H/N | planar placement frame | base | `boss` | USER | C | Boss/hardware | robust common case |
| Angled-surface boss | `supported-recipe` | H/H/N | explicit axis/frame | base | `boss` | USER | C | Boss/hardware | axis dominates surface |
| Curved-surface boss | `supported-recipe` | H/M/N | point + tangent/explicit axis | base | `boss` | USER | C | Boss/hardware | face topology more fragile |
| Variable-height boss | `supported-recipe` | H/H/N | native extent to selected entity | base | `boss` | USER | C | Boss/hardware | selected target must persist |
| Boss height from assembled mate | `supported-recipe` | H/H/N | shared datum / to-entity extent | base | `boss` | HW/USER | C | Boss/hardware | occurrence context required |
| Patterned bosses | `supported-recipe` | H/H/N | native pattern feature | base | `patterns` | USER | C | Patterns/config | copies share source parameters |
| Mirrored bosses | `supported-recipe` | H/H/N | native MirrorFeature | base | `patterns` | USER | C | Patterns/config | handed hardware must be checked |
| Autodesk native BossFeature | `supported-optional-extension-api` | H/H/Y | `BossFeatures.add` | entitlement unresolved | optional adapter | Autodesk rule | N | Product acceptance | base-account callability probe required |
| Simple raised lip | `supported-recipe` | H/H/N | offset sketch + Extrude Join | base | `seam` | FAB | C | Seams/seals | not native LipFeature |
| Simple recessed groove | `supported-recipe` | H/H/N | offset sketch + Extrude Cut | base | `seam` | FAB | C | Seams/seals | explicit target body |
| Coordinated lip/groove | `supported-recipe` | H/H/N | shared master path, join + cut | base | `seam` | FAB | Y for actual fit | Seams/seals | clearance coupon-sensitive |
| Tongue/groove | `supported-recipe` | H/H/N | paired profiles | base | `seam` | FAB | C | Seams/seals | same |
| Skirt/channel | `supported-recipe` | H/H/N | skirt join + receiver cut | base | `seam` | FAB | C | Seams/seals | path must meet supported rules |
| Skirt/channel bump snap | `supported-recipe` | H/H/N | seam + retention instance | base | `seam` + `retention` | MAT/FAB | Y | Retention | physical snap proof required |
| Light-exclusion labyrinth | `supported-recipe` | H/H/N | multiple alternating seam walls | base | `seam` | USER | N unless optical claim | Seams/seals | geometry only |
| Splash-resistant seam | `supported-recipe` | H/H/N | overlapping/draining seam | base | `seam` | USER | Y for ingress claim | Seams/seals | never implies IP rating |
| Flat gasket channel | `supported-recipe` | H/H/N | Extrude/Sweep Cut | base | `seal` | HW/standard | Y for seal claim | Seams/seals | source cross-section required |
| Gasket land | `supported-recipe` | H/H/N | native additive/retained land | base | `seal` | HW | Y for seal claim | Seams/seals | compression not certified |
| O-ring groove | `supported-recipe` | H/H/N | Extrude/Sweep Cut | base | `seal` | standard/HW | Y | Seams/seals | no generic gland default |
| Perimeter seal channel | `supported-recipe` | H/H/N | planar/nonplanar supported path | base | `seal` | HW/FAB | Y | Seams/seals | no ingress certification |
| Interrupted seal | `supported-recipe` | H/H/N | segmented path | base | `seal` | HW | Y | Seams/seals | interruptions explicit |
| Seal around fastener zones | `supported-recipe` | H/H/N | managed interruptions/stops | base | `seal` | HW | Y | Seams/seals | pressure distribution unvalidated |
| Seal around ports | `supported-recipe` | H/H/N | cutout-dependent path | base | `seal` | HW | Y | Seams/seals | managed port dependency |
| Compression stop | `supported-recipe` | H/H/N | discrete stop bosses/tabs | base | `seal` | HW | Y | Seams/seals | compression force unvalidated |
| Seam interruption around port | `supported-recipe` | H/H/N | port-published exclusion datums | base | `seam` | USER/FAB | C | Seams/seals | port is upstream owner |
| Seam interruption around hinge | `supported-recipe` | H/H/N | delimiter gap | base | `seam` | USER | C | Seams/seals | explicit delimiters |
| Seam interruption around latch | `supported-recipe` | H/H/N | delimiter gap | base | `seam` | USER | C | Seams/seals | explicit delimiters |
| Seam interruption around fastener | `supported-recipe` | H/H/N | delimiter/managed hardware gap | base | `seam` | HW | C | Seams/seals | explicit dependency |
| Registration key | `supported-recipe` | H/H/N | tab + receiver | base | `seam` | FAB | C | Seams/seals | no shear-rating claim |
| Anti-shear stop | `supported-recipe` | H/H/N | stop + receiver | base | `seam` | MAT/USER | Y for load claim | Seams/seals | geometry only |
| Local alignment tab/stop | `supported-recipe` | H/H/N | discrete tab/pocket | base | `seam` | FAB | C | Seams/seals | explicit station |
| Lead-in feature | `supported-shared-primitive` | H/H/N | Chamfer/profile geometry | base | `edge_treatments` | FAB | C | Native primitives | not a fit guarantee |
| Planar full seam | `supported-recipe` | H/H/N | named closed master sketch | base | `seam` | FAB | C | Seams/seals | robust path |
| Planar partial seam | `supported-recipe` | H/H/N | named open/segmented path | base | `seam` | FAB | C | Seams/seals | endpoints explicit |
| Tangent nonplanar seam | `supported-recipe` | H/M/N | Sweep | base | `seam` | FAB | C | Seams/seals | tight-radius failures surface |
| Segmented nonplanar seam | `supported-recipe` | H/M/N | multiple explicit sweeps | base | `seam` | FAB | C | Seams/seals | sharp corners explicit |
| Arbitrary non-tangent automatic nonplanar offset | `rejected-by-architecture` | N/N/N | none | n/a | none | n/a | n/a | Seams/seals | would become a custom geometry kernel |
| Cantilever parallel snap | `supported-recipe` | H/H/N | extrude/hook/groove | base | `retention` | MAT/FAB | Y | Retention | no stress certification |
| Cantilever perpendicular snap | `supported-recipe` | H/H/N | rotated hook/receiver | base | `retention` | MAT/FAB | Y | Retention | same |
| Internal hidden snap | `supported-recipe` | H/H/N | internal cantilever | base | `retention` | MAT/FAB | Y | Retention | service/release access explicit |
| Skirt bump snap | `supported-recipe` | H/H/N | bump + groove | base | `retention` | MAT/FAB | Y | Retention | coupon/cycles |
| Annular snap | `supported-recipe` | H/H/N | revolve + groove | base | `retention` | MAT/FAB | Y | Retention | physical engagement proof |
| Slotted annular snap | `supported-recipe` | H/H/N | annular + slots/pattern | base | `retention` | MAT/FAB | Y | Retention | finger/root behavior physical |
| Fingered lock ring | `supported-recipe` | H/H/N | ring + patterned fingers | base | `retention` | MAT/FAB | Y | Retention | fatigue unvalidated |
| Press-fit ring | `supported-recipe` | H/H/N | concentric ring pair | base | `retention` | FAB | Y | Retention | process-specific |
| Interference ring | `supported-recipe` | H/H/N | signed interference | base | `retention` | FAB | Y | Retention | coupon required |
| Keyed snap | `supported-recipe` | H/H/N | snap + tab/notch key | base | `retention` | MAT/FAB | Y | Retention | keyed rotation only |
| Dovetail retention | `supported-recipe` | H/H/N | linear/tangent sweep | base | `retention` | FAB | Y | Retention | arbitrary freeform excluded |
| Sliding-key retention | `supported-recipe` | H/H/N | key/rail + stop | base | `retention` | FAB | Y | Retention | service path explicit |
| Cylindrical bayonet retention | `supported-recipe` | H/M/N | lugs + swept L-slots | base | `retention` | MAT/FAB | Y | Retention | common-axis scope only |
| Arbitrary freeform bayonet | `ordinary-native-modeling-preferred` | M/M/N | manual sweep/slot modeling | base | documentation | USER | Y | Retention | poor reusable abstraction |
| PCB edge rest | `supported-recipe` | H/H/N | support tool + explicit join | base | `support` | USER/FAB | C | Supports | explicit contact surface |
| PCB corner support | `supported-recipe` | H/H/N | local support | base | `support` | USER/FAB | C | Supports | same |
| PCB support point | `supported-recipe` | H/H/N | pad/standoff | base | `support` | USER | C | Supports | explicit PCB datum |
| Converter shelf | `supported-recipe` | H/H/N | shelf + reinforcement | base | `support` | USER/MAT | Y for load claim | Supports | keep-outs explicit |
| Equipment shelf | `supported-recipe` | H/H/N | same | base | `support` | USER/MAT | Y for load claim | Supports | same |
| Local landing pad | `supported-recipe` | H/H/N | pad to selected extent | base | `support` | USER | C | Supports | top datum explicit |
| Curved-interior landing pad | `supported-recipe` | H/M/N | flat top + to-body bottom | base | `support` | USER | C | Supports | topology-sensitive target |
| Component saddle | `supported-recipe` | H/H/N | profile + trim/join | base | `support` | USER/FAB | C | Supports | component never mutated |
| Cylindrical cradle | `supported-recipe` | H/H/N | cylindrical saddle profile | base | `support` | USER/FAB | C | Supports | explicit diameter/axis |
| Profile-derived ledge | `supported-recipe` | H/H/N | explicit intersect/extent | base | `support` | USER | C | Supports | source profile must remain |
| Retention-lip support | `supported-recipe` | H/H/N | support + lip | base | `support` | MAT/FAB | Y if flexing | Supports | retention proof separate |
| Ribbed support | `supported-recipe` | H/H/N | support + reinforcement | base | `support` | MAT | Y for load claim | Supports | no structural claim |
| Gusseted support | `supported-recipe` | H/H/N | support + gusset | base | `support` | MAT | Y for load claim | Supports | same |
| Keepout-trimmed support | `supported-recipe` | H/H/N | explicit Combine cuts | base | `support` | USER | C | Supports | no automatic keepout discovery |
| Component-height-driven support | `supported-recipe` | H/H/N | native face/plane reference | base | `support` | USER | C | Supports | occurrence context required |
| Extent-to-body support | `supported-recipe` | H/H/N | native to-entity extent | base | `support` | USER | C | Supports | explicit body/face |
| Heat-set insert feature | `supported-shared-primitive` | H/H/N | insert pocket primitive | base | `holes_threads` | HW/FAB | Y | Boss/hardware | used standalone or by boss |
| Captive square nut feature | `supported-shared-primitive` | H/H/N | polygon pocket | base | `holes_threads` | HW/FAB | C | Boss/hardware | optional insertion slot |
| Captive hex nut feature | `supported-shared-primitive` | H/H/N | polygon pocket | base | `holes_threads` | HW/FAB | C | Boss/hardware | same |
| Screw clearance hole | `supported-native-api` | H/H/Y | HoleFeature clearance APIs | base | `holes_threads` | HW | C | Boss/hardware | modern API version gate |
| Counterbore | `supported-shared-primitive` | H/H/N | Hole or explicit seat | base | `holes_threads` | HW | C | Boss/hardware | hardware-sourced |
| Countersink | `supported-shared-primitive` | H/H/N | Hole or conical seat | base | `holes_threads` | HW | C | Boss/hardware | hardware-sourced |
| Spot face | `supported-shared-primitive` | H/H/N | axis-normal shallow cut | base | `holes_threads` | HW | C | Boss/hardware | axis required |
| Thread-forming pilot | `supported-shared-primitive` | H/H/N | sourced pilot cut | base | `holes_threads` | HW | Y | Boss/hardware | no generic default |
| Tapped hole | `supported-native-api` | H/H/Y | Hole tapped API / ThreadFeature | base | `holes_threads` | HW | C | Boss/hardware | version path differs |
| PCB standoff hardware | `supported-recipe` | H/H/N | boss/standoff composition | base | `boss` | HW | C | Boss/hardware | explicit top datum |
| Rectangular cutout | `supported-recipe` | H/H/N | sketch + explicit Extrude Cut | base | `cutout` | HW/FAB | C | Cutouts | none |
| Rounded-rectangle cutout | `supported-recipe` | H/H/N | constrained profile + cut | base | `cutout` | HW/FAB | C | Cutouts | none |
| Circular cutout | `supported-recipe` | H/H/N | circle + cut/Hole | base | `cutout` | HW/FAB | C | Cutouts | none |
| Arbitrary named planar profile | `supported-recipe` | H/H/N | associative named profile | base | `cutout` | HW/FAB | C | Cutouts | must be valid profile |
| Connector flange/recess | `supported-recipe` | H/H/N | primary cut + recess cut | base | `cutout` | HW/FAB | C | Cutouts | source connector dimensions |
| Recessed panel opening | `supported-recipe` | H/H/N | nested profile cuts | base | `cutout` | HW/FAB | C | Cutouts | none |
| Wall-normal cutout | `supported-recipe` | H/H/N | wall-normal frame + cut | base | `cutout` | HW | C | Cutouts | planar wall |
| Axis-normal angled cutout | `supported-recipe` | H/H/N | explicit axis frame | base | `cutout` | HW | C | Cutouts | axis authoritative |
| Curved-wall axis-projected cutout | `supported-recipe` | H/M/N | planar cutter through curved body | base | `cutout` | HW | C | Cutouts | not conformal profile |
| Arbitrary conformal double-curved cutout | `ordinary-native-modeling-preferred` | M/M/N | project-to-surface + native surface workflow | base | documentation | HW | C | Cutouts | topology too variable for bounded recipe |
| Cutout clearance offset | `supported-shared-primitive` | H/H/N | parameterized profile offset | base | `sketches` | FAB | C | Native primitives | coupon-sensitive |
| Cutout chamfer/fillet | `supported-shared-primitive` | H/H/N | native edge treatment | base | `edge_treatments` | FAB | N/C | Native primitives | downstream topology fragile |
| Cutout mounting holes | `supported-recipe` | H/H/N | explicit HoleFeatures | base | `cutout` | HW | C | Cutouts | mounting specs explicit |
| Cable exit support | `supported-recipe` | H/H/N | cutout + support | base | `strain_relief` | HW/USER | Y for pull claim | Cutouts | no pull-force validation |
| Cable clamp saddle | `supported-recipe` | H/H/N | saddle + hardware | base | `strain_relief` | HW | Y | Cutouts | cable dimensions explicit |
| Tie-wrap anchor | `supported-recipe` | H/H/N | bridge/slots | base | `strain_relief` | HW/FAB | Y for load claim | Cutouts | tie dimensions explicit |
| Zip-tie slot pair | `supported-recipe` | H/H/N | rounded cuts | base | `strain_relief` | HW/FAB | C | Cutouts | no strength claim |
| Cable retention bridge | `supported-recipe` | H/H/N | bridge extrude | base | `strain_relief` | USER/MAT | Y | Cutouts | physical load proof |
| Bend-radius guide | `supported-recipe` | H/H/N | explicit-radius path | base | `strain_relief` | HW | Y where critical | Cutouts | radius supplied |
| Flexible strain-relief fingers | `supported-recipe` | H/H/N | cantilever primitive | base | `strain_relief` | MAT | Y | Cutouts | fatigue proof required |
| Cable-channel transition | `supported-recipe` | H/M/N | tangent-continuous sweep | base | `strain_relief` | HW | C | Cutouts | discontinuous freeform transitions ordinary modeling |
| Wire-service loop retainer | `supported-recipe` | H/H/N | bridge/cantilever | base | `strain_relief` | USER/MAT | Y | Cutouts | physical retention proof |
| Straight rib | `supported-shared-primitive` | H/H/N | sketch/extrude/draft/fillet | base | `reinforcement` | MAT/FAB | Y for load claim | Supports | not native RibFeature |
| Radial boss rib | `supported-shared-primitive` | H/H/N | rib + circular pattern | base | `reinforcement` | MAT/FAB | Y | Supports | no structural analysis |
| Gusset | `supported-shared-primitive` | H/H/N | wedge/profile + join | base | `reinforcement` | MAT | Y | Supports | same |
| Triangular web | `supported-shared-primitive` | H/H/N | profile + join | base | `reinforcement` | MAT | Y | Supports | same |
| Wall-to-floor rib | `supported-shared-primitive` | H/H/N | explicit trim/join | base | `reinforcement` | MAT | Y | Supports | explicit participants |
| Boss-to-wall rib | `supported-shared-primitive` | H/H/N | managed boss dependency | base | `reinforcement` | MAT | Y | Supports | dependency blocks boss delete |
| Shelf reinforcement | `supported-shared-primitive` | H/H/N | support dependency | base | `reinforcement` | MAT | Y | Supports | no load certification |
| Patterned ribs | `supported-recipe` | H/H/N | native pattern | base | `patterns` | MAT | Y | Patterns/config | shared source parameters |
| Linear slot vents | `supported-recipe` | H/H/N | seed cut + pattern | base | `vent` | USER/FAB | N | Vents/coupons | thermal performance not claimed |
| Rectangular vent arrays | `supported-recipe` | H/H/N | native rectangular pattern | base | `vent` | USER/FAB | N | Vents/coupons | same |
| Circular hole arrays | `supported-recipe` | H/H/N | native pattern | base | `vent` | USER/FAB | N | Vents/coupons | same |
| Hex/honeycomb vent region | `supported-recipe` | H/H/N | staggered patterns + mask | base | `vent` | USER/FAB | N | Vents/coupons | bounded planar region |
| Clipped arbitrary planar vent region | `supported-recipe` | H/M/N | patterned tools + explicit mask | base | `vent` | USER | N | Vents/coupons | clipped boundary cells |
| Automatic arbitrary whole-cell selection | `rejected-by-architecture` | N/N/N | none | n/a | none | n/a | n/a | Vents/coupons | would require custom containment engine |
| Louver array | `ordinary-native-modeling-preferred` | H/H/N | sketch/cut/hood/pattern manually | base | documentation | USER/FAB | N | Vents/coupons | airflow/orientation ambiguity outweighs abstraction value |
| Sliding-clearance coupon | `supported-recipe` | H/H/N | explicit candidate stations | base | `coupon` | FAB | Y | Vents/coupons | no automatic scoring |
| Press-fit coupon | `supported-recipe` | H/H/N | explicit candidate stations | base | `coupon` | FAB | Y | Vents/coupons | same |
| Pin/hole coupon | `supported-recipe` | H/H/N | explicit candidate stations | base | `coupon` | FAB | Y | Vents/coupons | same |
| Nut-clearance coupon | `supported-recipe` | H/H/N | polygon candidates | base | `coupon` | HW/FAB | Y | Vents/coupons | hardware-specific |
| Heat-insert coupon | `supported-recipe` | H/H/N | sourced insert candidates | base | `coupon` | HW/FAB | Y | Vents/coupons | installation test required |
| Lip/groove coupon | `supported-recipe` | H/H/N | mating seam stations | base | `coupon` | FAB | Y | Vents/coupons | same process as production |
| Snap-engagement coupon | `supported-recipe` | H/H/N | snap candidates | base | `coupon` | MAT/FAB | Y | Vents/coupons | cycle/strain proof separate |
| Dovetail coupon | `supported-recipe` | H/H/N | rail/receiver candidates | base | `coupon` | FAB | Y | Vents/coupons | same |
| Connector-cutout coupon | `supported-recipe` | H/H/N | opening candidates | base | `coupon` | HW/FAB | Y | Vents/coupons | actual connector required |
| Shipped FDM feature-rule catalog | `supported-recipe` | H/H/N | plugin data → Fusion parameters | base | `rules` | mixed | depends | Foundations | not Autodesk Plastic Rules |
| Design-local rule overrides | `supported-recipe` | H/H/N | Fusion user parameters/attrs | base | `rules` | mixed | depends | Foundations | Fusion is state owner |
| User reusable preset | `supported-recipe` | H/H/N | explicit plugin configuration action | base | `rules` | mixed | depends | Foundations | never auto-written by ordinary modeling |
| Autodesk PlasticRule objects | `supported-optional-extension-api` | H/H/Y | public PlasticRules API | entitlement unresolved | optional adapter | Autodesk | N | Product acceptance | intentionally not toolkit dependency |
| Configuration-aware parameter update | `supported-native-api` | H/H/Y | Fusion Configurations + parameters | base/current API probe | `context` | USER | N/C | Patterns/config | reacquire after activation |
| Configuration-aware suppression authoring | `unsupported-public-api` | ?/?/? | probe required | unresolved | `context` | USER | N | Patterns/config | enable only after public API/live proof |
| Rectangular managed pattern | `supported-native-api` | H/H/Y | native pattern | base | `patterns` | USER | inherits source | Patterns/config | generated members share source |
| Circular managed pattern | `supported-native-api` | H/H/Y | native pattern | base | `patterns` | USER | inherits source | Patterns/config | same |
| Path managed pattern | `supported-native-api` | H/H/Y | `PathPatternFeatures` | base | `patterns` | USER | inherits source | Patterns/config | supported path required |
| Managed mirror | `supported-native-api` | H/H/Y | `MirrorFeatures` | base | `patterns` | USER | inherits source | Patterns/config | same-type input rules |
| Native extension Snap Fit API | `unsupported-public-api` | ?/?/? | no specialized creation API established in public docs searched | extension UI | none | Autodesk | n/a | Product acceptance | current-build probe required |
| Native extension Lip API | `unsupported-public-api` | ?/?/? | no specialized creation API established in public docs searched | extension UI | none | Autodesk | n/a | Product acceptance | current-build probe required |
| Native extension Rest API | `unsupported-public-api` | ?/?/? | no specialized creation API established in public docs searched | extension UI | none | Autodesk | n/a | Product acceptance | current-build probe required |
