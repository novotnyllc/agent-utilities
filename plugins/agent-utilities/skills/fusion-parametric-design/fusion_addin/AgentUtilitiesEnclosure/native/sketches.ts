/**
 * Sketch profile creation: planar, polygon, and offset profiles.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/sketches.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


export function makePlanarProfile(
  component: Any,
  name: string,
  plane: Any,
  shape: string,
  dims: Record<string, Any> = {},
): Any | null {
  const sketches = component.sketches;
  const sketch = sketches.add(plane);
  sketch.name = name;

  if (shape === "rectangle" && "width" in dims && "height" in dims) {
    const w = dims.width;
    const h = dims.height;
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
      adsk.core.Point3D.create(-w / 2, -h / 2, 0),
      adsk.core.Point3D.create(w / 2, h / 2, 0),
    );
  } else if (
    shape === "rounded_rectangle" &&
    "width" in dims && "height" in dims && "corner_radius" in dims
  ) {
    roundedRect(sketch, dims.width, dims.height, dims.corner_radius);
  } else if (shape === "circle" && "diameter" in dims) {
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
      adsk.core.Point3D.create(0, 0, 0),
      dims.diameter / 2,
    );
  } else if (shape === "slot" && "length" in dims && "width" in dims) {
    slot(sketch, dims.length, dims.width);
  } else {
    return null;
  }
  return sketch;
}

function roundedRect(sketch: Any, w: number, h: number, r: number): void {
  const lines = sketch.sketchCurves.sketchLines;
  const arcs = sketch.sketchCurves.sketchArcs;
  const hw = w / 2 - r;
  const hh = h / 2 - r;
  const lineSegs: Array<[[number, number], [number, number]]> = [
    [[-hw, hh], [hw, hh]],
    [[hw, hh], [hw, -hh]],
    [[hw, -hh], [-hw, -hh]],
    [[-hw, -hh], [-hw, hh]],
  ];
  for (const [[x1, y1], [x2, y2]] of lineSegs) {
    lines.addByTwoPoints(adsk.core.Point3D.create(x1, y1, 0), adsk.core.Point3D.create(x2, y2, 0));
  }
  const pi = Math.PI;
  const arcSpecs: Array<[[number, number], number, number]> = [
    [[hw, hh], 0, pi / 2],
    [[-hw, hh], pi / 2, pi],
    [[-hw, -hh], pi, (3 * pi) / 2],
    [[hw, -hh], (3 * pi) / 2, 2 * pi],
  ];
  for (const [[cx, cy], a1, a2] of arcSpecs) {
    const p1 = adsk.core.Point3D.create(cx + r * Math.cos(a1), cy + r * Math.sin(a1), 0);
    const p2 = adsk.core.Point3D.create(cx + r * Math.cos(a2), cy + r * Math.sin(a2), 0);
    arcs.addByCenterStartSweep(adsk.core.Point3D.create(cx, cy, 0), p1, a2 - a1);
  }
}

function slot(sketch: Any, length: number, width: number): void {
  const r = width / 2;
  const half = (length - width) / 2;
  sketch.sketchCurves.sketchLines.addByTwoPoints(
    adsk.core.Point3D.create(-half, r, 0),
    adsk.core.Point3D.create(half, r, 0),
  );
  sketch.sketchCurves.sketchLines.addByTwoPoints(
    adsk.core.Point3D.create(half, -r, 0),
    adsk.core.Point3D.create(-half, -r, 0),
  );
  sketch.sketchCurves.sketchArcs.addByCenterStartSweep(
    adsk.core.Point3D.create(half, 0, 0),
    adsk.core.Point3D.create(half, r, 0),
    Math.PI,
  );
  sketch.sketchCurves.sketchArcs.addByCenterStartSweep(
    adsk.core.Point3D.create(-half, 0, 0),
    adsk.core.Point3D.create(-half, -r, 0),
    Math.PI,
  );
}

export function makePolygonProfile(
  component: Any,
  name: string,
  plane: Any,
  sides: number,
  acrossFlats: number,
): Any | null {
  let circumradius: number;
  if (sides === 4) {
    circumradius = acrossFlats / Math.sqrt(2);
  } else if (sides === 6) {
    circumradius = acrossFlats / Math.sqrt(3);
  } else {
    circumradius = acrossFlats / (2 * Math.cos(Math.PI / sides));
  }

  const sketches = component.sketches;
  const sketch = sketches.add(plane);
  sketch.name = name;
  const lines = sketch.sketchCurves.sketchLines;
  const pts: Any[] = [];
  for (let i = 0; i < sides; i++) {
    const angle = (2 * Math.PI * i) / sides + Math.PI / sides;
    pts.push(adsk.core.Point3D.create(
      circumradius * Math.cos(angle),
      circumradius * Math.sin(angle),
      0,
    ));
  }
  for (let i = 0; i < sides; i++) {
    lines.addByTwoPoints(pts[i], pts[(i + 1) % sides]);
  }
  return sketch;
}

export function makeOffsetProfile(
  component: Any,
  name: string,
  sourceSketch: Any,
  offsetExpr: string,
): Any | null {
  const sketches = component.sketches;
  const plane = "referencePlane" in sourceSketch ? sourceSketch.referencePlane : sourceSketch;
  const target = sketches.add(plane);
  target.name = name;
  const curves = adsk.core.ObjectCollection.create();
  for (let i = 0; i < sourceSketch.sketchCurves.count; i++) {
    curves.add(sourceSketch.sketchCurves.item(i));
  }
  const result = target.offset(
    curves,
    adsk.core.ValueInput.createByString(offsetExpr),
    adsk.core.Point3D.create(0, 0, 0),
  );
  return result !== null && result !== undefined ? target : null;
}
