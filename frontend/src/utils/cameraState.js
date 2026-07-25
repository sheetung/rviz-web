const cloneFiniteVector = (vector) => {
  if (!vector) return null;
  const cloned = {
    x: Number(vector.x),
    y: Number(vector.y),
    z: Number(vector.z),
  };
  return Object.values(cloned).every(Number.isFinite) ? cloned : null;
};

export const cloneCameraState = (cameraState) => {
  const position = cloneFiniteVector(cameraState?.position);
  const target = cloneFiniteVector(cameraState?.target);
  if (!position || !target) return null;

  const up = cloneFiniteVector(cameraState.up) || { x: 0, y: 0, z: 1 };
  const projection =
    cameraState.projection === "orthographic" ? "orthographic" : "perspective";
  const zoom = Number(cameraState.zoom);

  return {
    position,
    target,
    up,
    projection,
    zoom: Number.isFinite(zoom) && zoom > 0 ? zoom : 1,
  };
};
