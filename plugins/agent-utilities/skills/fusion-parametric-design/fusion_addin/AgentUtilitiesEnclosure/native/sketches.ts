/**
 * Sketch profile creation: planar, polygon, and offset profiles.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/sketches.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;



/** Fusion sketch geometry consumes database centimetres; recipe dimensions are
 * millimetres. Convert at the sketch boundary so a "20 mm" cutout is not a
 * 20 cm one. */
function mmToCm(v: number): number {
  return v / 10;
}

export function makePlanarProfile(
  component: Any,
  name: string,
  plane: Any,
  shape: string,
  dims: Record<string, Any> = {},
  opts: { offsetX?: number; offsetY?: number } = {},
): Any | null {
  const sketches = component.sketches;
  const sketch = sketches.add(plane);
  sketch.name = name;

  if (shape === "rectangle" && "width" in dims && "height" in dims) {
    const w = dims.width;
    const h = dims.height;
    const ox = opts.offsetX ?? 0;
    const oy = opts.offsetY ?? 0;
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
      adsk.core.Point3D.create(mmToCm(ox - w / 2), mmToCm(oy - h / 2), 0),
      adsk.core.Point3D.create(mmToCm(ox + w / 2), mmToCm(oy + h / 2), 0),
    );
  } else if (
    shape === "rounded_rectangle" &&
    "width" in dims && "height" in dims && "corner_radius" in dims
  ) {
    const rox = mmToCm(opts.offsetX ?? 0);
    const roy = mmToCm(opts.offsetY ?? 0);
    roundedRect(sketch, mmToCm(dims.width), mmToCm(dims.height), mmToCm(dims.corner_radius), rox, roy);
  } else if (shape === "circle" && "diameter" in dims) {
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
      adsk.core.Point3D.create(
        mmToCm(opts.offsetX ?? 0),
        mmToCm(opts.offsetY ?? 0),
        0,
      ),
      mmToCm(dims.diameter / 2),
    );
  } else if (shape === "slot" && "length" in dims && "width" in dims) {
    slot(sketch, dims.length, dims.width, opts.offsetX ?? 0, opts.offsetY ?? 0);
  } else {
    return null;
  }
  return sketch;
}

function roundedRect(sketch: Any, w: number, h: number, r: number, ox = 0, oy = 0): void {
  const lines = sketch.sketchCurves.sketchLines;
  const arcs = sketch.sketchCurves.sketchArcs;
  if (2 * r >= Math.min(w, h)) {
    return;
  }
  const hw = w / 2 - r;
  const hh = h / 2 - r;
  // Tangent-point geometry: edges run between arc ENDPOINTS on the true
  // bounding box (x=±(hw+r)=±w/2, y=±(hh+r)=±h/2), so every line end
  // coincides exactly with an arc start/end and sketch.profiles.count === 1.
  const lineSegs: Array<[[number, number], [number, number]]> = [
    [[-hw + ox, oy + hh + r], [hw + ox, oy + hh + r]],       // top: y = +h/2
    [[ox + hw + r, oy - hh], [ox + hw + r, oy + hh]],         // right: x = +w/2
    [[hw + ox, oy - (hh + r)], [-hw + ox, oy - (hh + r)]],    // bottom: y = -h/2
    [[ox - (hw + r), oy - hh], [ox - (hw + r), oy + hh]],     // left: x = -w/2
  ];
  for (const [[x1, y1], [x2, y2]] of lineSegs) {
    lines.addByTwoPoints(adsk.core.Point3D.create(x1, y1, 0), adsk.core.Point3D.create(x2, y2, 0));
  }
  const pi = Math.PI;
  // Each arc starts where a line ends and sweeps -90 deg (clockwise) to the
  // next line's start, closing the loop TR -> BR -> BL -> TL.
  // Explicit start points per corner (center cx,cy then start sx,sy):
  const specs: Array<[number, number, number, number]> = [
    [ox + hw, oy + hh, ox + hw, oy + (hh + r)],               // TR: top-edge end -> right-edge start
    [ox + hw, oy - hh, ox + (hw + r), oy - hh],               // BR: right-edge end -> bottom-edge start
    [ox - hw, oy - hh, ox - hw, oy - (hh + r)],               // BL: bottom-edge end -> left-edge start
    [ox - hw, oy + hh, ox - (hw + r), oy + hh],               // TL: left-edge end -> top-edge start
  ];
  for (const [cx, cy, sx, sy] of specs) {
    arcs.addByCenterStartSweep(
      adsk.core.Point3D.create(cx, cy, 0),
      adsk.core.Point3D.create(sx, sy, 0),
      -pi / 2,
    );
  }
}

function slot(sketch: Any, length: number, width: number, offsetX = 0, offsetY = 0): void {
  const r = mmToCm(width / 2);
  const half = mmToCm((length - width) / 2);
  const ox = mmToCm(offsetX);
  const oy = mmToCm(offsetY);
  sketch.sketchCurves.sketchLines.addByTwoPoints(
    adsk.core.Point3D.create(ox - half, oy + r, 0),
    adsk.core.Point3D.create(ox + half, oy + r, 0),
  );
  sketch.sketchCurves.sketchLines.addByTwoPoints(
    adsk.core.Point3D.create(ox + half, oy - r, 0),
    adsk.core.Point3D.create(ox - half, oy - r, 0),
  );
  sketch.sketchCurves.sketchArcs.addByCenterStartSweep(
    adsk.core.Point3D.create(ox + half, oy, 0),
    adsk.core.Point3D.create(ox + half, oy + r, 0),
    Math.PI,
  );
  sketch.sketchCurves.sketchArcs.addByCenterStartSweep(
    adsk.core.Point3D.create(ox - half, oy, 0),
    adsk.core.Point3D.create(ox - half, oy - r, 0),
    Math.PI,
  );
}

export function makePolygonProfile(
  component: Any,
  name: string,
  plane: Any,
  sides: number,
  acrossFlats: number,
  opts: { offsetX?: number; offsetY?: number } = {},
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
  const ox = opts.offsetX ?? 0;
  const oy = opts.offsetY ?? 0;
  for (let i = 0; i < sides; i++) {
    const angle = (2 * Math.PI * i) / sides + Math.PI / sides;
    pts.push(adsk.core.Point3D.create(
      mmToCm(ox + circumradius * Math.cos(angle)),
      mmToCm(oy + circumradius * Math.sin(angle)),
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
  opts: { side?: "outward" | "inward" } = {},
): Any | null {
  // Side is explicit: outward offsets along +X of the sketch plane, inward
  // negates the expression. Callers state intent instead of relying on an
  // implicit direction default.
  const sketches = component.sketches;
  const plane = "referencePlane" in sourceSketch ? sourceSketch.referencePlane : sourceSketch;
  const target = sketches.add(plane);
  target.name = name;
  const curves = adsk.core.ObjectCollection.create();
  for (let i = 0; i < sourceSketch.sketchCurves.count; i++) {
    curves.add(sourceSketch.sketchCurves.item(i));
  }
  // Sketch.offset signature: offset(curves, directionPoint, offsetValue)
  const signedExpr = opts.side === "inward" ? `-${offsetExpr}` : offsetExpr;
  const result = target.offset(
    curves,
    adsk.core.Point3D.create(1, 0, 0),
    adsk.core.ValueInput.createByString(signedExpr),
  );
  return result !== null && result !== undefined ? target : null;
}
