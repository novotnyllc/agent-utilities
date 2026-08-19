"""The live runtime capability probe.

Fusion's embedded Python is not the host's, and it auto-updates.  Every fact this
skill would otherwise hardcode -- the interpreter tag triple, which directories on
``sys.path`` are writable, which preview mesh and construction APIs exist -- moves
without warning, and a hardcoded tag rots into a ``ModuleNotFoundError`` that
reads like "not installed".  So the probe records the tags rather than asserting
them, keyed by the Fusion version they belong to.

The tag triple is the point.  ``(python_version, abi, platform)`` are exactly the
values pip's ``--python-version`` / ``--abi`` / ``--platform`` flags take, and
they cannot be derived from the host: Fusion reports a ``sysconfig`` platform of
``macosx-10.15-universal2`` while loading a ``macosx_11_0_arm64`` wheel.  Where a
value cannot be derived from what the interpreter actually reported, this probe
records it as unavailable.  It never guesses one, because a guessed tag produces
a confidently wrong pip invocation.

**The probe starts no process, ever.**  Inside Fusion the running interpreter's
executable path is the Fusion application binary, so anything that launches it --
a child process, a worker pool, pip's own bootstrap -- starts a second copy of
Fusion on the user's machine.  This has actually happened.  The emitted source is
asserted free of every construct that could do it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_reconstruction import _validate_body_binding

if TYPE_CHECKING:
    from .manifest import Manifest


PROBE_SPEC_FIELDS = {"component_path", "body_name", "dump_dir"}

# Probed by import, reported by name. `ensurepip` is imported and never touched:
# its bootstrap would launch the interpreter's executable, which here is Fusion.
PROBED_MODULES = (
    "base64",
    "ctypes",
    "ensurepip",
    "hashlib",
    "os",
    "packaging",
    "requests",
    "secrets",
    "sqlite3",
    "struct",
    "tempfile",
    "uuid",
    "numpy",
)

# (owner module, owner class, attribute). Every one is reported individually; a
# missing owner names the owner, not a blanket "capabilities missing".
PROBED_APIS = (
    ("fusion", "MeshBody", "mesh"),
    ("fusion", "MeshBody", "transform"),
    ("fusion", "PolygonMesh", "nodeCoordinates"),
    ("fusion", "PolygonMesh", "triangleNodeIndices"),
    ("fusion", "PolygonMesh", "triangleFaceGroupTempIds"),
    ("fusion", "PolygonMesh", "triangleCount"),
    ("fusion", "PolygonMesh", "compareWith"),
    ("fusion", "Component", "sketches"),
    ("fusion", "Component", "constructionPlanes"),
    ("fusion", "Component", "meshBodies"),
    ("fusion", "Sketch", "sketchCurves"),
    ("fusion", "Sketch", "geometricConstraints"),
    ("fusion", "Sketch", "sketchDimensions"),
    ("fusion", "Features", "extrudeFeatures"),
    ("fusion", "Features", "revolveFeatures"),
    ("fusion", "Features", "holeFeatures"),
    ("fusion", "Features", "filletFeatures"),
    ("fusion", "BRepBody", "pointContainment"),
    ("core", "Matrix3D", "asArray"),
)


def validate_probe_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the optional probe spec, which binds a body and a dump directory.

    Without it the probe still records the interpreter and the API surface; the
    face-group histogram and the write round-trip are then reported
    ``not-requested`` rather than passed.  Absent is not the same as fine.
    """
    if spec is None:
        return []
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "probe-spec-must-be-object",
                "probe_spec",
                "A capability probe spec must be an object, or absent.",
            )
        ]
    _reject_unknown_fields(issues, spec, PROBE_SPEC_FIELDS, "probe_spec")
    _validate_body_binding(
        issues,
        {key: spec[key] for key in ("component_path", "body_name") if key in spec},
        "probe_spec",
        "probe-spec-invalid-binding",
    )
    dump_dir = spec.get("dump_dir")
    if not isinstance(dump_dir, str) or not dump_dir.strip():
        issues.append(
            ValidationIssue(
                "probe-spec-invalid-dump-dir",
                "probe_spec.dump_dir",
                "dump_dir must name the directory the extraction will write its dump to; the probe "
                "writes one small file there and removes it, which is what settles whether a file "
                "written from Fusion's interpreter is readable at all.",
            )
        )
    return issues


def emit_capability_probe_script(manifest: "Manifest", spec: Any = None) -> str:
    """Emit the read-only capability probe. It creates nothing and starts nothing."""
    from .scripts import _json_literal, _script_prelude

    issues = validate_probe_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "probe_spec": (
            None
            if spec is None
            else {
                "component_path": spec["component_path"],
                "body_name": spec["body_name"],
                "dump_dir": str(spec["dump_dir"]).strip(),
            }
        ),
        "modules": list(PROBED_MODULES),
        "apis": [list(entry) for entry in PROBED_APIS],
    }

    transaction = '''PROBE_SPECS = json.loads(__PROBE_SPECS__)

import hashlib
import os
import stat
import sys
import sysconfig

PROCESS_NOTE = (
    "This probe starts nothing. Inside Fusion the running interpreter's executable path is the "
    "Fusion application binary, so any construct that launches it -- a child process, a worker "
    "pool, pip's own installer entry point -- starts a second copy of Fusion on the user's machine. "
    "The executable path is recorded below as evidence of exactly that."
)
TAG_NOTE = (
    "python_version, abi and platform are pip's --python-version / --abi / --platform flags. They "
    "are recorded, never hardcoded: Fusion auto-updates its interpreter, and a stale tag fails as "
    "ModuleNotFoundError, which reads like 'not installed'. A value this probe could not derive "
    "from what the interpreter reported is null, not a guess."
)
PLATFORM_NOTE = (
    "The wheel platform tag is NOT derivable from sysconfig here: this interpreter reports one "
    "platform string and loads wheels built for another. Only packaging.tags.sys_tags() is "
    "authoritative. Without it, confirm the platform tag against an actual install before using it."
)


def _probe_modules(names):
    result = {}
    for name in names:
        try:
            __import__(name)
        except BaseException as error:
            # A raising import is reported with its message, never omitted: a name
            # missing from this map would read as a name nobody asked about.
            result[name] = {
                "available": False,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        else:
            result[name] = {"available": True}
    return result


def _module_version(name):
    module = sys.modules.get(name)
    if module is None:
        return None
    value = getattr(module, "__version__", None)
    return str(value) if value is not None else None


def _abi_from_ext_suffix(ext_suffix):
    """Derive the wheel ABI tag from EXT_SUFFIX, or refuse to derive one."""
    if not ext_suffix:
        return None, "unavailable"
    parts = str(ext_suffix).split(".")
    if len(parts) < 2:
        return None, "unavailable"
    fields = parts[1].split("-")
    if len(fields) < 2 or fields[0] != "cpython" or not fields[1].isdigit():
        return None, "unavailable"
    return "cp" + fields[1], "EXT_SUFFIX"


def _packaging_tags():
    try:
        import packaging.tags
    except BaseException as error:
        return {"available": False, "error_type": type(error).__name__, "error": str(error)}
    try:
        tags = ["-".join([tag.interpreter, tag.abi, tag.platform]) for tag in packaging.tags.sys_tags()]
    except BaseException as error:
        return {"available": False, "error_type": type(error).__name__, "error": str(error)}
    return {"available": True, "tags": tags[:64], "tag_count": len(tags)}


def _sys_path_entries():
    entries = []
    for raw in list(sys.path):
        entry = {"path": raw, "exists": False, "is_dir": False, "writable": False}
        if not raw:
            entry["note"] = "empty entry: the current working directory"
            entries.append(entry)
            continue
        try:
            info = os.stat(raw)
        except BaseException as error:
            entry["error_type"] = type(error).__name__
            entry["error"] = str(error)
            entries.append(entry)
            continue
        entry["exists"] = True
        entry["is_dir"] = stat.S_ISDIR(info.st_mode)
        entry["mode"] = oct(stat.S_IMODE(info.st_mode))
        entry["owner_uid"] = info.st_uid
        try:
            entry["writable"] = bool(os.access(raw, os.W_OK))
        except BaseException as error:
            entry["writable"] = False
            entry["error_type"] = type(error).__name__
            entry["error"] = str(error)
        entries.append(entry)
    return entries


def _probe_apis(specs):
    present = {}
    missing = []
    for module_name, class_name, attribute in specs:
        module = getattr(adsk, module_name, None)
        owner_name = "adsk." + module_name + "." + class_name
        full_name = owner_name + "." + attribute
        if module is None:
            present[full_name] = None
            missing.append("adsk." + module_name)
            continue
        owner = getattr(module, class_name, None)
        if owner is None:
            present[full_name] = None
            if owner_name not in missing:
                missing.append(owner_name)
            continue
        found = hasattr(owner, attribute)
        present[full_name] = found
        if not found:
            missing.append(full_name)
    return present, missing


def _face_groups(design, binding):
    component_path = binding["component_path"]
    if component_path:
        _, occurrence_map, duplicates = _root_context_occurrence_map(design.rootComponent)
        if component_path in duplicates:
            return {"status": "unavailable", "reason": "duplicate-semantic-path"}
        occurrence = occurrence_map.get(component_path)
        if occurrence is None:
            return {"status": "unavailable", "reason": "component-path-missing"}
        component = occurrence.component
    else:
        component = design.rootComponent
    mesh_bodies = getattr(component, "meshBodies", None)
    if mesh_bodies is None:
        return {"status": "unavailable", "reason": "Component.meshBodies is absent"}
    body = None
    for index in range(mesh_bodies.count):
        candidate = mesh_bodies.item(index)
        if getattr(candidate, "name", None) == binding["body_name"]:
            body = candidate
            break
    if body is None:
        return {"status": "unavailable", "reason": "no mesh body named " + repr(binding["body_name"])}
    mesh = getattr(body, "mesh", None)
    if mesh is None:
        return {"status": "unavailable", "reason": "MeshBody.mesh is absent"}
    triangle_count = getattr(mesh, "triangleCount", None)
    try:
        raw = getattr(mesh, "triangleFaceGroupTempIds", None)
    except Exception as error:
        return {"status": "unavailable", "reason": "triangleFaceGroupTempIds raised: " + str(error)}
    if raw is None:
        return {
            "status": "absent",
            "triangle_count": triangle_count,
            "reason": "Fusion reported no triangleFaceGroupTempIds on this mesh.",
        }
    try:
        ids = [int(value) for value in raw]
    except Exception as error:
        return {"status": "unavailable", "reason": "triangleFaceGroupTempIds unreadable: " + str(error)}
    histogram = {}
    for value in ids:
        key = str(value)
        histogram[key] = histogram.get(key, 0) + 1
    return {
        "status": "present",
        "triangle_count": triangle_count,
        "id_count": len(ids),
        "group_count": len(histogram),
        "histogram": histogram,
        "single_group": len(histogram) == 1,
        "covers_every_triangle": triangle_count is not None and len(ids) == int(triangle_count),
    }


def _write_roundtrip(dump_dir):
    payload = ("fusion-design capability probe " + MANIFEST_SHA256).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    path = os.path.join(dump_dir, "fusion-design-capability-probe.tmp")
    try:
        os.makedirs(dump_dir, exist_ok=True)
        handle = open(path, "wb")
        try:
            handle.write(payload)
        finally:
            handle.close()
        handle = open(path, "rb")
        try:
            read_back = handle.read()
        finally:
            handle.close()
    except BaseException as error:
        return {
            "status": "failed",
            "path": path,
            "error_type": type(error).__name__,
            "error": str(error),
            "consequence": (
                "A file written from Fusion's interpreter is not readable here, so mesh extraction "
                "must use its chunked-stdout fallback, with that fallback's declared size ceiling."
            ),
        }
    result = {"status": "ok", "path": path, "bytes": len(read_back)}
    if hashlib.sha256(read_back).hexdigest() != digest:
        result["status"] = "failed"
        result["error"] = "the file read back with different bytes than were written"
    try:
        os.remove(path)
        result["removed"] = True
    except BaseException as error:
        result["removed"] = False
        result["remove_error"] = str(error)
    return result


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        checked = []
        report = {
            "kind": "capability-probe",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "creates_geometry": False,
            "ok_means": (
                "The probe ran and recorded what it found. It does not mean every capability is "
                "present: read missing_apis, modules, face_groups and dump_write_roundtrip, each of "
                "which reports its own outcome."
            ),
            "checked": checked,
            "failures": [],
            "process_note": PROCESS_NOTE,
            "tag_note": TAG_NOTE,
            "platform_note": PLATFORM_NOTE,
        }

        ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
        implementation = sys.implementation
        report["interpreter"] = {
            "version": sys.version,
            "version_info": [sys.version_info[0], sys.version_info[1], sys.version_info[2]],
            "implementation_name": getattr(implementation, "name", None),
            "implementation_version": ".".join(
                [str(part) for part in list(getattr(implementation, "version", []))[:3]]
            ) or None,
            "ext_suffix": ext_suffix,
            "sysconfig_platform": sysconfig.get_platform(),
            "byteorder": sys.byteorder,
            "maxsize": sys.maxsize,
            # Recorded because it is the hazard: this is Fusion, not a Python.
            "interpreter_executable_path": getattr(sys, "executable", None),
        }
        abi, abi_source = _abi_from_ext_suffix(ext_suffix)
        packaging_tags = _packaging_tags()
        report["packaging_tags"] = packaging_tags
        wheel_platform = None
        platform_source = "unavailable"
        if packaging_tags.get("available") and packaging_tags.get("tags"):
            wheel_platform = packaging_tags["tags"][0].split("-")[-1]
            platform_source = "packaging.tags.sys_tags"
        report["pip_tags"] = {
            "python_version": str(sys.version_info[0]) + "." + str(sys.version_info[1]),
            "python_version_source": "sys.version_info",
            "implementation": "cp" if getattr(implementation, "name", None) == "cpython" else None,
            "implementation_source": "sys.implementation.name",
            "abi": abi,
            "abi_source": abi_source,
            "platform": wheel_platform,
            "platform_source": platform_source,
            "sysconfig_platform_is_not_a_wheel_tag": sysconfig.get_platform(),
        }
        checked.append("interpreter-tags")

        report["sys_path"] = _sys_path_entries()
        report["writable_sys_path"] = [
            entry["path"] for entry in report["sys_path"] if entry.get("writable") and entry.get("is_dir")
        ]
        checked.append("sys-path")

        modules = _probe_modules(PROBE_SPECS["modules"])
        for name in list(modules):
            if modules[name]["available"]:
                version = _module_version(name)
                if version is not None:
                    modules[name]["version"] = version
        report["modules"] = modules
        checked.append("module-imports")

        apis, missing = _probe_apis(PROBE_SPECS["apis"])
        report["apis"] = apis
        report["missing_apis"] = missing
        checked.append("api-presence")

        binding = PROBE_SPECS["probe_spec"]
        if binding is None:
            not_requested = {
                "status": "not-requested",
                "reason": (
                    "No probe spec bound a mesh body and a dump directory, so neither the face-group "
                    "histogram nor the write round-trip was attempted. Not attempted is not a pass."
                ),
            }
            report["face_groups"] = not_requested
            report["dump_write_roundtrip"] = dict(not_requested)
        else:
            report["face_groups"] = _face_groups(design, binding)
            checked.append("face-groups")
            _pump_events(app, design, target_document)
            report["dump_write_roundtrip"] = _write_roundtrip(binding["dump_dir"])
            checked.append("dump-write-roundtrip")

        report["ok"] = True
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "capability-probe",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "creates_geometry": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace("__PROBE_SPECS__", _json_literal(specs))
