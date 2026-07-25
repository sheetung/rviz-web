import assert from "node:assert/strict";
import test from "node:test";

import { shouldUseNonTypingSelect } from "../src/utils/inputCapabilities.js";

test("uses a non-typing select for coarse pointer devices", () => {
  const matchMedia = (query) => ({ matches: query === "(pointer: coarse)" });
  assert.equal(
    shouldUseNonTypingSelect({ matchMedia, maxTouchPoints: 0 }),
    true,
  );
});

test("uses a non-typing select when touch points are the only available signal", () => {
  assert.equal(
    shouldUseNonTypingSelect({ matchMedia: undefined, maxTouchPoints: 5 }),
    true,
  );
});

test("keeps searchable selects for mouse-driven devices", () => {
  const matchMedia = () => ({ matches: false });
  assert.equal(
    shouldUseNonTypingSelect({ matchMedia, maxTouchPoints: 0 }),
    false,
  );
});

test("keeps searchable selects on a touch laptop with a hovering primary pointer", () => {
  const matchMedia = () => ({ matches: false });
  assert.equal(
    shouldUseNonTypingSelect({ matchMedia, maxTouchPoints: 5 }),
    false,
  );
});
