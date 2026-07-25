export const poseDampingAlpha = (
  deltaMilliseconds,
  timeConstantMilliseconds,
) => {
  const delta = Math.max(0, Number(deltaMilliseconds) || 0);
  const timeConstant = Math.max(1, Number(timeConstantMilliseconds) || 1);
  return 1 - Math.exp(-delta / timeConstant);
};
