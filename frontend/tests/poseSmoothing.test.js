import assert from "node:assert/strict";
import test from "node:test";

import { poseDampingAlpha } from "../src/utils/poseSmoothing.js";

test("pose damping is frame-rate independent", () => {
  const singleFrame = poseDampingAlpha(32, 70);
  const splitFrame = poseDampingAlpha(16, 70);
  const combinedSplitFrame = 1 - (1 - splitFrame) * (1 - splitFrame);
  assert.ok(Math.abs(singleFrame - combinedSplitFrame) < 1e-12);
});

test("pose damping clamps invalid time inputs safely", () => {
  assert.equal(poseDampingAlpha(-10, 70), 0);
  assert.ok(poseDampingAlpha(16, 0) > 0);
  assert.ok(poseDampingAlpha(16, 70) < 1);
});
