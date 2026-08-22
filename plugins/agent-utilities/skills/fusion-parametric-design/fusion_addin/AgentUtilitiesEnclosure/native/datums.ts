/**
 * Named construction planes, axes, and points via public Fusion API.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/datums.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


export function makeNamedPlane(
  component: Any,
  name: string,
  method: string,
  kwargs: Record<string, Any> = {},
): Any | null {
  const planes = component.constructionPlanes;
  const existing = planes.itemByName(name);
  if (existing !== null && existing !== undefined) {
    return existing;
  }

  const inputObj = planes.createInput();
  if (method === "offset" && "face" in kwargs && "offset" in kwargs) {
    inputObj.setByOffset(
      kwargs.face,
      adsk.core.ValueInput.createByString(kwargs.offset),
    );
  } else if (method === "angle" && "line" in kwargs && "face" in kwargs && "angle" in kwargs) {
    inputObj.setByAngle(
      kwargs.line,
      adsk.core.ValueInput.createByString(kwargs.angle),
      kwargs.face,
    );
  } else if (method === "three_point" && ["p1", "p2", "p3"].every((k) => k in kwargs)) {
    inputObj.setByThreePoints(kwargs.p1, kwargs.p2, kwargs.p3);
  } else if (method === "by_face" && "face" in kwargs) {
    inputObj.setByFace(kwargs.face);
  } else {
    return null;
  }

  const plane = planes.add(inputObj);
  plane.name = name;
  return plane;
}

export function makeNamedAxis(
  component: Any,
  name: string,
  method: string,
  kwargs: Record<string, Any> = {},
): Any | null {
  const axes = component.constructionAxes;
  const existing = axes.itemByName(name);
  if (existing !== null && existing !== undefined) {
    return existing;
  }

  const inputObj = axes.createInput();
  if (method === "two_point" && "p1" in kwargs && "p2" in kwargs) {
    inputObj.setByTwoPoints(kwargs.p1, kwargs.p2);
  } else if (method === "edge" && "edge" in kwargs) {
    inputObj.setByEdge(kwargs.edge);
  } else if (method === "cylinder" && "face" in kwargs) {
    inputObj.setByCylinder(kwargs.face);
  } else if (method === "plane_normal" && "face" in kwargs) {
    inputObj.setByNormal(kwargs.face);
  } else {
    return null;
  }

  const axis = axes.add(inputObj);
  axis.name = name;
  return axis;
}

export function makeNamedPoint(
  component: Any,
  name: string,
  method: string,
  kwargs: Record<string, Any> = {},
): Any | null {
  const points = component.constructionPoints;
  const existing = points.itemByName(name);
  if (existing !== null && existing !== undefined) {
    return existing;
  }

  const inputObj = points.createInput();
  if (method === "coordinates" && "point3d" in kwargs) {
    inputObj.setByPoint(kwargs.point3d);
  } else if (method === "on_edge" && "edge" in kwargs && "param" in kwargs) {
    inputObj.setByEdgeParameter(kwargs.edge, kwargs.param);
  } else if (method === "center" && "sphere" in kwargs) {
    inputObj.setBySphere(kwargs.sphere);
  } else {
    return null;
  }

  const pt = points.add(inputObj);
  pt.name = name;
  return pt;
}
