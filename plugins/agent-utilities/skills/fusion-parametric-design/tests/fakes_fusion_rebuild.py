"""A Fusion double good enough to drive the U4/U5 transactions offline.

It models the parts the emitted interpreters actually touch: a timeline of named
features, sketch points that can be made to move when a constraint is applied,
user parameters with expressions, and bodies whose physical properties respond
to the parameters.  Everything a test wants to go wrong is injectable, so every
refusal branch is driven by the real emitted code rather than asserted about it.
"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any


class FakeList:
    def __init__(self, items=()):
        self.items = list(items)

    @property
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]


class FakePoint:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class FakeSketchPoint:
    def __init__(self, x, y):
        self.geometry = FakePoint(x, y)


class FakeCurve:
    def __init__(self, sketch, kind, start, end, radius=None):
        self.sketch = sketch
        self.kind = kind
        self.startSketchPoint = start
        self.endSketchPoint = end
        self.radius = radius
        self.isValid = True
        self.entityToken = f"token-{kind}-{id(self)}"

    def deleteMe(self):
        self.isValid = False
        return True


class FakeCurveCollection:
    def __init__(self, sketch):
        self.sketch = sketch

    def _as_sketch_point(self, value):
        """Fusion turns a Point3D argument into a real SketchPoint on the sketch.

        Passing an existing SketchPoint back in shares it, which is exactly what
        the transaction relies on to chain a closed profile without explicit
        coincidences.
        """
        if isinstance(value, FakeSketchPoint):
            return value
        return self.sketch._point(value.x, value.y)

    def addByTwoPoints(self, start, end):
        return self.sketch._add_curve(
            "line", self._as_sketch_point(start), self._as_sketch_point(end)
        )

    def addByThreePoints(self, start, mid, end):
        return self.sketch._add_curve(
            "arc", self._as_sketch_point(start), self._as_sketch_point(end)
        )

    def addByCenterRadius(self, centre, radius):
        point = self._as_sketch_point(centre)
        return self.sketch._add_curve("circle", point, point, radius=radius)


class FakeConstraint:
    def __init__(self, kind, entities):
        self.kind = kind
        self.entities = entities
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class FakeGeometricConstraints:
    def __init__(self, sketch):
        self.sketch = sketch
        self.applied = []

    def _add(self, kind, *entities):
        self.sketch._on_constraint(kind, entities)
        handle = FakeConstraint(kind, entities)
        self.applied.append(handle)
        return handle

    def addHorizontal(self, line):
        return self._add("horizontal", line)

    def addVertical(self, line):
        return self._add("vertical", line)

    def addParallel(self, a, b):
        return self._add("parallel", a, b)

    def addPerpendicular(self, a, b):
        return self._add("perpendicular", a, b)

    def addTangent(self, a, b):
        return self._add("tangent", a, b)

    def addConcentric(self, a, b):
        return self._add("concentric", a, b)

    def addEqual(self, a, b):
        return self._add("equal", a, b)

    def addCoincident(self, point, entity):
        return self._add("coincident", point, entity)


class FakeParameter:
    def __init__(self, expression):
        self.expression = expression


class FakeDimension:
    def __init__(self, kind, parameter):
        self.kind = kind
        self.parameter = parameter
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class FakeSketchDimensions:
    def __init__(self, sketch):
        self.sketch = sketch
        self.applied = []

    def addRadialDimension(self, curve, text):
        return self._add("radius", curve)

    def addOffsetDimension(self, curve, other, text):
        return self._add("offset", curve)

    def addDistanceDimension(self, first, second, orientation, text):
        handle = FakeDimension("distance-" + str(orientation), FakeParameter(""))
        self.applied.append(handle)
        return handle

    def _add(self, kind, curve):
        self.sketch._on_constraint("dimension:" + kind, (curve,))
        handle = FakeDimension(kind, FakeParameter(""))
        self.applied.append(handle)
        return handle


class FakeProfile:
    def __init__(self, area, centroid=None):
        self._area = area
        self._centroid = tuple(centroid) if centroid is not None else (0.0, 0.0, 0.0)

    def areaProperties(self):
        return SimpleNamespace(
            area=self._area,
            centroid=SimpleNamespace(
                x=self._centroid[0], y=self._centroid[1], z=self._centroid[2]
            ),
        )


class FakeSketch:
    def __init__(self, design, plane, behaviour):
        self.design = design
        self.plane = plane
        self.behaviour = behaviour
        self.name = "sketch"
        self.points = []
        self.curves = []
        self.sketchCurves = SimpleNamespace(
            sketchLines=FakeCurveCollection(self),
            sketchArcs=FakeCurveCollection(self),
            sketchCircles=FakeCurveCollection(self),
        )
        self.geometricConstraints = FakeGeometricConstraints(self)
        self.sketchDimensions = FakeSketchDimensions(self)
        self.originPoint = FakeSketchPoint(0.0, 0.0)
        self.isFullyConstrained = behaviour.get("fully_constrained", True)
        self.isValid = True
        self.entityToken = f"token-sketch-{id(self)}"

    @property
    def sketchPoints(self):
        sketch = self

        class Points(FakeList):
            def add(self, point):
                created = FakeSketchPoint(point.x, point.y)
                sketch.points.append(created)
                return created

        return Points(self.points)

    @property
    def profiles(self):
        # What Fusion is declared to enumerate for this sketch. `profile_regions`
        # is the multi-loop case: the test states the area and centroid of every
        # region, which is the response the executor matches its plan against.
        # Re-deriving regions from the fake curves would be reimplementing
        # Fusion's solver in a double, which proves nothing about Fusion.
        regions = self.behaviour.get("profile_regions")
        if isinstance(regions, dict):
            # Keyed by sketch name: Fusion returns a different enumeration for
            # every sketch, and one declared list for a whole design would only
            # ever describe one of them.
            regions = regions.get(self.name)
        if regions is not None:
            return FakeList(
                [
                    FakeProfile(row["area_cm2"], tuple(row["centroid_cm"]) + (0.0,))
                    for row in regions
                ]
            )
        count = self.behaviour.get("profile_count", 1)
        return FakeList([FakeProfile(10.0 + index) for index in range(count)])

    def _point(self, x, y):
        point = FakeSketchPoint(x, y)
        self.points.append(point)
        return point

    def _add_curve(self, kind, start, end, radius=None):
        if self.behaviour.get("raise_on_curve") == len(self.curves):
            raise RuntimeError("the sketch solver rejected this curve")
        curve = FakeCurve(self, kind, start, end, radius)
        self.curves.append(curve)
        return curve

    def _on_constraint(self, kind, entities):
        error = self.behaviour.get("raise_on_constraint")
        if error is not None and error == kind:
            raise RuntimeError("solver rejected " + kind)
        move = self.behaviour.get("displace_on_constraint")
        if move is not None and move[0] == kind:
            # Millimetres in the transaction; the fake stores centimetres.
            self.points[0].geometry.x += move[1] / 10.0

    def deleteMe(self):
        self.isValid = False
        return True


class FakeFeature:
    def __init__(self, design, kind, object_type):
        self.design = design
        self.kind = kind
        self.name = "unnamed"
        self.objectType = object_type
        self.isValid = True
        self.entityToken = f"token-{kind}-{id(self)}"
        self.errorOrWarningMessage = ""
        self.healthy = True
        # The edge ids overlap between consecutive features by default, which is
        # what gives a fillet between *two* features an edge to find.
        edge_ids = design.behaviour.get("feature_edge_ids", {}).get(kind)
        if edge_ids is None:
            edge_ids = [1, 2, 3]
        # An extrude's faces come partitioned, and the partition is a box's: each
        # side face meets the start cap along one edge, the end cap along
        # another, and its two neighbours along the two edges that are interior
        # to the side set. A fillet inside one feature asks for exactly those,
        # so the double has to have them rather than one undifferentiated pile.
        # Its own block of edge ids, because an edge interior to one feature is
        # not an edge some other feature also owns -- only the ids seeded above
        # are deliberately shared, and those are what a two-feature fillet finds.
        sides = design.behaviour.get("extrude_side_count", 4)
        base = getattr(design, "_face_edge_base", 0) + 1000
        design._face_edge_base = base
        boxes = design.behaviour.get("edge_boxes")
        expose = not design.behaviour.get("no_edge_box")
        self._start_faces = [FakeFace(edge_ids + [base + i for i in range(sides)], boxes, expose)]
        self._end_faces = [
            FakeFace(edge_ids + [base + 100 + i for i in range(sides)], boxes, expose)
        ]
        self._side_faces = [
            FakeFace(
                [base + i, base + 100 + i, base + 200 + i, base + 200 + (i - 1) % sides],
                boxes,
                expose,
            )
            for i in range(sides)
        ]
        self._faces = [*self._start_faces, *self._side_faces, *self._end_faces]

    def _face_set(self, name, faces):
        if self.design.behaviour.get("no_feature_faces"):
            raise AttributeError(name)
        # Only an ExtrudeFeature partitions its faces. A revolve does not, which
        # is why the planner never asks one to round an edge inside itself.
        if name != "faces" and self.kind != "extrude":
            raise AttributeError(name)
        return FakeList(faces)

    @property
    def faces(self):
        return self._face_set("faces", self._faces)

    @property
    def startFaces(self):
        return self._face_set("startFaces", self._start_faces)

    @property
    def endFaces(self):
        return self._face_set("endFaces", self._end_faces)

    @property
    def sideFaces(self):
        return self._face_set("sideFaces", self._side_faces)

    def deleteMe(self):
        self.isValid = False
        self.design.timeline_items = [
            item for item in self.design.timeline_items if item.entity is not self
        ]
        return True


class FakeBoundingBox:
    def __init__(self, low, high):
        self.minPoint = FakePoint(*low)
        self.maxPoint = FakePoint(*high)


class FakeEdge:
    """An edge with a place, because a fillet has to pick one edge out of many.

    ``edge_boxes`` in the behaviour maps a temp id to its box in centimetres; an
    id nobody placed gets a distinct unit box along the diagonal, so two edges
    are never accidentally at the same distance from anything. ``no_edge_box``
    strips the member entirely, which is the Fusion that cannot answer where its
    edges are.
    """

    def __init__(self, temp_id, boxes=None, expose_box=True):
        self.tempId = temp_id
        self.entityToken = f"token-edge-{temp_id}"
        if expose_box:
            low, high = (boxes or {}).get(
                temp_id, ((temp_id, temp_id, temp_id), (temp_id + 1, temp_id + 1, temp_id + 1))
            )
            self.boundingBox = FakeBoundingBox(low, high)


class FakeFace:
    def __init__(self, edges, boxes=None, expose_box=True):
        self._edges = [FakeEdge(temp_id, boxes, expose_box) for temp_id in edges]
        self.entityToken = f"token-face-{id(self)}"

    @property
    def edges(self):
        return FakeList(self._edges)


class FakeHoleInput:
    """Hole inputs differ from extrude inputs: setDistanceExtent takes one value."""

    def __init__(self, diameter):
        self.diameter = diameter
        self.point = None
        self.extent = None

    def setPositionBySketchPoint(self, point):
        self.point = point

    def setDistanceExtent(self, value):
        self.extent = value


class FakeFilletInput:
    def __init__(self):
        self.edge_sets = []

    def addConstantRadiusEdgeSet(self, edges, radius, tangent_chain):
        self.edge_sets.append((edges, radius, tangent_chain))


class FakeFeatureInput:
    def __init__(self):
        self.extent = None

    def setDistanceExtent(self, symmetric, value):
        self.extent = value

    def setAngleExtent(self, symmetric, value):
        self.extent = value


class FakeFeatureCollection:
    def __init__(self, component, kind, object_type):
        self.component = component
        self.kind = kind
        self.object_type = object_type

    def createInput(self, *args):
        return FakeFeatureInput()

    def add(self, feature_input):
        design = self.component.design
        if design.behaviour.get("raise_on_feature") == self.component.feature_count:
            self.component.feature_count += 1
            raise RuntimeError("Fusion could not build this feature")
        self.component.feature_count += 1
        feature = FakeFeature(design, self.kind, self.object_type)
        design.add_timeline(feature)
        self.component.bodies.append(
            FakeBody(design, f"Body{len(self.component.bodies) + 1}")
        )
        return feature


class FakeHoleFeatures(FakeFeatureCollection):
    def createSimpleInput(self, diameter):
        return FakeHoleInput(diameter)


class FakeFilletFeatures(FakeFeatureCollection):
    def createInput(self):
        return FakeFilletInput()


class FakeBody:
    def __init__(self, design, name):
        self.design = design
        self.name = name
        self.entityToken = f"token-body-{name}"

    @property
    def volume(self):
        return self.design.volume_cm3()

    def physicalProperties(self, accuracy):
        centre = self.design.centroid_cm()
        return SimpleNamespace(
            volume=self.design.volume_cm3(),
            centerOfMass=FakePoint(*centre),
        )

    @property
    def boundingBox(self):
        low, high = self.design.bbox_cm()
        return SimpleNamespace(minPoint=FakePoint(*low), maxPoint=FakePoint(*high))


class FakeConstructionPlane:
    def __init__(self, offset):
        self.offset = offset
        self.isValid = True
        self.entityToken = f"token-plane-{id(self)}"

    def deleteMe(self):
        self.isValid = False
        return True


class FakeConstructionPlanes:
    def createInput(self):
        return SimpleNamespace(
            offset=None,
            setByOffset=lambda plane, value: None,
        )

    def add(self, plane_input):
        return FakeConstructionPlane(getattr(plane_input, "offset", None))


class FakeComponent:
    def __init__(self, design, name):
        self.design = design
        self.name = name
        self.bodies = []
        self.feature_count = 0
        self.sketch_list = []
        self.xYConstructionPlane = SimpleNamespace(name="XY")
        self.xZConstructionPlane = SimpleNamespace(name="XZ")
        self.yZConstructionPlane = SimpleNamespace(name="YZ")
        self.xConstructionAxis = SimpleNamespace(name="X")
        self.yConstructionAxis = SimpleNamespace(name="Y")
        self.zConstructionAxis = SimpleNamespace(name="Z")
        self.constructionPlanes = FakeConstructionPlanes()
        self.features = SimpleNamespace(
            extrudeFeatures=FakeFeatureCollection(self, "extrude", "adsk::fusion::ExtrudeFeature"),
            revolveFeatures=FakeFeatureCollection(self, "revolve", "adsk::fusion::RevolveFeature"),
            holeFeatures=FakeHoleFeatures(self, "hole", "adsk::fusion::HoleFeature"),
            filletFeatures=FakeFilletFeatures(self, "fillet", "adsk::fusion::FilletFeature"),
        )

    @property
    def sketches(self):
        component = self

        class Sketches:
            def add(self, plane):
                sketch = FakeSketch(component.design, plane, component.design.behaviour)
                component.sketch_list.append(sketch)
                component.design.add_timeline(sketch, object_type="adsk::fusion::Sketch")
                return sketch

        return Sketches()

    @property
    def bRepBodies(self):
        return FakeList(self.bodies)

    @property
    def occurrences(self):
        return FakeList()


class FakeOccurrence:
    def __init__(self, component):
        self.component = component
        self.isValid = True
        self.entityToken = f"token-occurrence-{component.name}"

    def deleteMe(self):
        self.isValid = False
        return True


class FakeOccurrences:
    def __init__(self, design):
        self.design = design
        self.items = []

    @property
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]

    def addNewComponent(self, transform):
        component = FakeComponent(self.design, "unnamed")
        occurrence = FakeOccurrence(component)
        self.items.append(occurrence)
        return occurrence


class FakeUserParameter:
    def __init__(self, design, name, expression, unit, comment):
        self.design = design
        self.name = name
        self._expression = expression
        self.unit = unit
        self.comment = comment
        self.isValid = True

    @property
    def expression(self):
        return self._expression

    @expression.setter
    def expression(self, value):
        self._expression = value
        self.design.on_expression(self.name, value)

    def deleteMe(self):
        self.isValid = False
        self.design.parameters = [p for p in self.design.parameters if p is not self]
        return True


class FakeUserParameters:
    def __init__(self, design):
        self.design = design

    @property
    def count(self):
        return len(self.design.parameters)

    def item(self, index):
        return self.design.parameters[index]

    def add(self, name, value, unit, comment):
        parameter = FakeUserParameter(self.design, name, value, unit, comment)
        self.design.parameters.append(parameter)
        return parameter


class FakeTimelineItem:
    def __init__(self, entity, health):
        self.entity = entity
        self.healthState = health


class FakeDesign:
    """One design double, shared by both transactions' tests."""

    def __init__(self, behaviour=None, parameters=(), root_name="Root"):
        self.behaviour = dict(behaviour or {})
        self.rootComponent = FakeComponent(self, root_name)
        self.root_occurrences = FakeOccurrences(self)
        self.parameters = [
            FakeUserParameter(self, name, expression, "mm", "")
            for name, expression in parameters
        ]
        self.timeline_items = []
        self.userParameters = FakeUserParameters(self)
        self.compute_count = 0
        self.expression_log = []
        self._volume_cm3 = self.behaviour.get("volume_cm3", 8.0)
        self._centroid_cm = list(self.behaviour.get("centroid_cm", (1.0, 1.0, 1.0)))
        self._bbox_cm = (
            list(self.behaviour.get("bbox_low_cm", (0.0, 0.0, 0.0))),
            list(self.behaviour.get("bbox_high_cm", (2.0, 2.0, 2.0))),
        )
        self.rootComponent.occurrences_override = self.root_occurrences

    # -- observables -----------------------------------------------------
    def volume_cm3(self):
        return self._volume_cm3

    def centroid_cm(self):
        return tuple(self._centroid_cm)

    def bbox_cm(self):
        return (tuple(self._bbox_cm[0]), tuple(self._bbox_cm[1]))

    def on_expression(self, name, value):
        self.expression_log.append((name, value))
        response = (self.behaviour.get("responses") or {}).get(name)
        if response is None:
            return
        response(self, name, value)

    def computeAll(self):
        self.compute_count += 1
        hook = self.behaviour.get("on_compute")
        if hook is not None:
            hook(self)
        return True

    def findEntityByToken(self, token):
        if token in (self.behaviour.get("unresolvable_tokens") or ()):
            return None
        return SimpleNamespace(entityToken=token)

    # -- timeline --------------------------------------------------------
    def add_timeline(self, entity, object_type=None):
        if object_type is not None and not hasattr(entity, "objectType"):
            entity.objectType = object_type
        self.timeline_items.append(FakeTimelineItem(entity, "healthy"))

    @property
    def timeline(self):
        return FakeList(
            [
                FakeTimelineItem(item.entity, "healthy" if getattr(item.entity, "healthy", True) else "error")
                for item in self.timeline_items
            ]
        )

    @property
    def allOccurrences(self):
        return self.root_occurrences


class _FakeObjectCollection(list):
    def add(self, item):
        self.append(item)
        return True


def _patch_occurrences(design):
    """Make ``design.rootComponent.occurrences`` the design's own collection."""
    component = design.rootComponent
    type(component).occurrences = property(lambda self: self.design.root_occurrences)
    type(component).allOccurrences = property(lambda self: self.design.root_occurrences)
    return design


def make_design(**kwargs):
    return _patch_occurrences(FakeDesign(**kwargs))


def load_transaction(source: str, design, document_name: str, on_events=None) -> dict:
    """Execute a generated transaction against the doubles and return its globals.

    ``on_events`` runs on every ``adsk.doEvents`` so a test can do what a user
    does: change the document out from under a running transaction.
    """
    import sys

    adsk = ModuleType("adsk")
    core = ModuleType("adsk.core")
    fusion = ModuleType("adsk.fusion")
    adsk.core = core
    adsk.fusion = fusion
    fusion.FeatureHealthStates = SimpleNamespace(
        HealthyFeatureHealthState="healthy",
        WarningFeatureHealthState="warning",
        ErrorFeatureHealthState="error",
        RolledBackFeatureHealthState="rolled-back",
        SuppressedFeatureHealthState="suppressed",
        UnknownFeatureHealthState="unknown",
    )
    fusion.FeatureOperations = SimpleNamespace(
        NewBodyFeatureOperation="new-body",
        JoinFeatureOperation="join",
        CutFeatureOperation="cut",
    )
    fusion.CalculationAccuracy = SimpleNamespace(VeryHighCalculationAccuracy="very-high")
    fusion.BoundingBoxEntityTypes = SimpleNamespace(AllEntitiesBoundingBoxEntityType="all")
    core.ValueInput = SimpleNamespace(createByString=lambda expression: expression)
    core.Point3D = SimpleNamespace(create=lambda x, y, z: FakePoint(x, y, z))
    core.ObjectCollection = SimpleNamespace(create=lambda: _FakeObjectCollection())
    fusion.DimensionOrientations = SimpleNamespace(
        HorizontalDimensionOrientation="horizontal",
        VerticalDimensionOrientation="vertical",
    )
    core.Matrix3D = SimpleNamespace(
        create=lambda: SimpleNamespace(setWithArray=lambda values: True, asArray=lambda: [])
    )
    document = SimpleNamespace(name=document_name)
    app = SimpleNamespace(activeDocument=document, activeProduct=design, version="2.0.99")
    adsk.doEvents = (lambda: None) if on_events is None else (lambda: on_events(document, app))
    core.Application = SimpleNamespace(get=lambda: app)
    fusion.Design = SimpleNamespace(cast=lambda product: product)

    modules = {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion}
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        namespace: dict[str, Any] = {"__name__": "generated_transaction"}
        exec(compile(source, "<generated>", "exec"), namespace)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return namespace
