import assert from "node:assert/strict";
import test from "node:test";

import { cloneCameraState } from "../src/utils/cameraState.js";

test("clones a valid configured camera without sharing nested objects", () => {
  const source = {
    position: { x: 1, y: 2, z: 3 },
    target: { x: 4, y: 5, z: 6 },
    up: { x: 0, y: 0, z: 1 },
    zoom: 2,
    projection: "orthographic",
  };
  const cloned = cloneCameraState(source);

  assert.deepEqual(cloned, source);
  source.position.x = 99;
  assert.equal(cloned.position.x, 1);
});

test("rejects camera states without finite position and target vectors", () => {
  assert.equal(cloneCameraState(null), null);
  assert.equal(cloneCameraState({ position: { x: 1, y: 2, z: 3 } }), null);
  assert.equal(
    cloneCameraState({
      position: { x: Number.NaN, y: 2, z: 3 },
      target: { x: 0, y: 0, z: 0 },
    }),
    null,
  );
});

test("normalizes optional camera fields to safe defaults", () => {
  assert.deepEqual(
    cloneCameraState({
      position: { x: 1, y: 2, z: 3 },
      target: { x: 0, y: 0, z: 0 },
    }),
    {
      position: { x: 1, y: 2, z: 3 },
      target: { x: 0, y: 0, z: 0 },
      up: { x: 0, y: 0, z: 1 },
      projection: "perspective",
      zoom: 1,
    },
  );
});
