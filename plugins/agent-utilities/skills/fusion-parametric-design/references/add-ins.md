# Free add-ins as expert tools

Free Autodesk App Store add-ins are part of the expert Fusion operator's
toolkit. An expert knows what is installed, reaches for the add-in that owns a
job instead of hand-rolling its output, and recommends a free add-in without
hesitation when one would clearly help — that is the opposite of the
paid-extension posture: extensions cost real money and get at most one gentle
mention, while free add-ins are low-friction and recommending them is
expected. Both stay secondary to getting the task done.

## The normative part: discover, prefer, be honest

1. **Discover what is installed, live.** `adsk.core.Application.get().scripts`
   enumerates every registered script and add-in with `name` and `isRunning` —
   one small read-only probe. `app.userInterface.commandDefinitions` and the
   workspace toolbar panels carry every command's id, name, and tooltip,
   including add-in-contributed panels; a bounded read of the relevant panels
   grounds "what tools exist here" in fact. An installed-but-not-running
   add-in registers no commands until it is started in Utilities ▸ Add-Ins.
2. **Prefer the tool that owns the job.** When an installed add-in or a
   discovered native utility command does natively what the task needs — gap
   analysis instead of pairwise Measure calls, minimized bounding box instead
   of hand-derived orientation, a gear generator instead of a hand-drawn
   involute — use it, and name it to the user.
3. **Be honest about invocability, and climb the ladder.** A command id can be
   fired with `commandDefinitions.itemById(id).execute()`, but on a
   dialog-driven command that only *opens* the dialog. For any capability
   that looks UI-only:
   1. **Probe the API at time of use** — Fusion updates, and a recorded
      "no API exists" is a hint of where to expect a gap, never permanent
      truth.
   2. **Drive the UI directly** when the capability is genuinely UI-only and
      the session has a computer-use/screen-control capability: open the
      command, fill the dialog, then verify the result through the API and a
      screenshot. Same discipline as everything else — bounded, one action at
      a time, single live writer, never while another agent mutates the
      document.
   3. **Ask the user to run the command** only when the session has no
      computer-use capability at all — one line, specific.
   The simple native equivalent wins whenever it is faster than any of this.
4. **Recommend missing add-ins proactively.** When a task would benefit from a
   known add-in the user does not have: name it, say what it does for the task
   at hand, and point at its Autodesk App Store listing. The store's free Mac
   catalog is
   <https://marketplace.autodesk.com/search?productIds=FSN&pricingModel=FREE&targetPlatform=mac>.

## Known-useful free add-ins (standing knowledge, not a contract)

Standing knowledge of free App Store add-ins worth knowing, verified against
their store listings, published sources, and a live command-registry probe.
Nothing here asserts what any session has: the probe above, not this table,
decides what is installed and running, and the table exists so the agent can
recognize an installed tool and recommend a missing one by name. Store column:
exact Autodesk App Store listing name to search (linked where a listing URL is
stable). Command ids are as the add-ins register them.

| Add-in | Reaches for it to… | Invocability | Store listing |
|---|---|---|---|
| ParametricText (thomasa88) | Bind sketch text to user parameters/document properties — version and part-number labels that update themselves; pairs with the decals/markings doctrine | `thomasa88_ParametricText_Map` opens the dialog; `thomasa88_ParametricText_Update` recomputes and is safely script-fired | "ParametricText" |
| DirectName (thomasa88) | Prompt-to-name every feature/body/sketch/component at creation — automates naming-at-creation doctrine, including part numbers and descriptions | Passive event handlers; panel toggles configure it; nothing to run | "DirectName" |
| 3D Printing Essentials (Autodesk) | Print pre-flight: Minimum Part Gap Analysis, Minimum Wall Thickness, Interlock/Z-Removability/Trapped Volume analyses, Minimize Bounding Box, Optimize Orientation, Label, Duplicate Components, Add Parts | Dialog-driven; ids are `Autodesk_Contents_*` (literal — do not "correct" it) | "3D Printing Essentials" |
| Timeline manager (kriomant) | Group/ungroup/split/extend/collapse timeline runs — timeline organization at scale | 13 `kriomant_Contents_*` commands act on the current timeline selection, no dialogs — script-firable after selection | "Timeline manager" |
| Display Utilities / ShowHidden (Autodesk) | Bulk show all bodies/components or reveal hidden ones — visibility hygiene during inspection | `SAB_CmdId`, `SAC_CmdId`, `SHB_CmdId`, `SHC_CmdId` — fire-and-forget | "Display Utilities" |
| Toggle Bodies | Toggle visibility of all bodies in the active component tree — see inside an assembly in one action | `toggle_bodies` — fire-and-forget | "Toggle Bodies" |
| Wire Generator | Generate spline wire/cable runs between two points with radius/arc/variance parameters — the wiring doctrine's preferred generator when installed | `NC1` opens the dialog; user or computer-use drives it | [Wire Generator](https://apps.autodesk.com/FUSION/en/Detail/Index?id=1866257341742728249) |
| Helical Gear+ | Real involute external/internal/rack gears, any helix angle, worms included | `helicalGearPlus` opens the dialog | "Helical Gear +" |
| Gridfinity Generator | Parametric Gridfinity bins and baseplates | `LevMishin_GridfinityGenerator_cmdBin` / `_cmdBaseplate` dialogs | "Gridfinity Generator" |
| Box Joint (Suska) | Parametric box/finger joints as an editable custom feature | `Suska_BoxJointCreate` / `Suska_BoxJointEdit` dialogs, selection-heavy | "Box Joint" |
| Airfoil Tools (Ocean Hydro) | Real airfoil sections, wings, struts, ducts, propellers, turbines, polar analysis, Reynolds calculators | `airfoil_toolbar_button_aft_*` dialogs | "Airfoil Tools" |
| Hestus Sketch Helper | AI constraint suggestions to close out under-constrained sketches | `Hestus_SketchHelper` palette; interactive | [Sketch Helper](https://apps.autodesk.com/FUSION/en/Detail/Index?id=4418895848074294698) |
| Lattice Design Suite (TETMET) | Conformal lattice design for lightweighting | `TETMET_lds_ASLM*` dialogs; registers commands only when started | [Lattice Design Suite](https://apps.autodesk.com/FUSION/en/Detail/Index?id=2696878352524201267) |
| NoComponentWarn (thomasa88) | Warn when a feature lands outside any component | Purely passive; no command | "NoComponentWarn" |
| GitHubToFusion360 (JBTechLab) | Install a script/add-in straight from a GitHub/GitLab URL | A Script, not an add-in — run from Utilities ▸ Add-Ins ▸ Scripts | "GitHubToFusion360" |

Native utility commands discovered the same way are equally fair game — the
UTILITIES tab's Inspect panel carries the full native Inspect set, and
Fusion's own Compute All lives at `FusionComputeAllCommand`.

Add-ins are code running inside Fusion: prefer well-known, widely used ones,
and treat an add-in's output like any other geometry — inspected with native
tools, never assumed correct.
