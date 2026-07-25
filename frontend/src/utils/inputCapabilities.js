export const shouldUseNonTypingSelect = ({
  matchMedia = globalThis.window?.matchMedia?.bind(globalThis.window),
  maxTouchPoints = globalThis.navigator?.maxTouchPoints || 0,
} = {}) => {
  if (typeof matchMedia !== "function") return maxTouchPoints > 0;

  try {
    if (matchMedia?.("(pointer: coarse)")?.matches) return true;
    return maxTouchPoints > 0 && matchMedia("(hover: none)")?.matches === true;
  } catch {
    return maxTouchPoints > 0;
  }
};
