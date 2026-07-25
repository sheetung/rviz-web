import * as THREE from 'three'

const HEIGHT_COLOR_FRAGMENT_GLSL = `
varying float vPointCloudHeight;

float pointCloudHueChannel(float minimumValue, float maximumValue, float hue) {
  float normalizedHue = fract(hue);
  if (normalizedHue < 1.0 / 6.0) {
    return minimumValue + (maximumValue - minimumValue) * 6.0 * normalizedHue;
  }
  if (normalizedHue < 1.0 / 2.0) return maximumValue;
  if (normalizedHue < 2.0 / 3.0) {
    return minimumValue + (maximumValue - minimumValue) * (2.0 / 3.0 - normalizedHue) * 6.0;
  }
  return minimumValue;
}

vec3 pointCloudHeightColor(float height) {
  float normalizedHeight = clamp((height + 2.0) / 4.0, 0.0, 1.0);
  float hue = (1.0 - normalizedHeight) * (240.0 / 360.0);
  float saturation = 0.8;
  float lightness = 0.6;
  float maximumValue = lightness + saturation - lightness * saturation;
  float minimumValue = 2.0 * lightness - maximumValue;
  return vec3(
    pointCloudHueChannel(minimumValue, maximumValue, hue + 1.0 / 3.0),
    pointCloudHueChannel(minimumValue, maximumValue, hue),
    pointCloudHueChannel(minimumValue, maximumValue, hue - 1.0 / 3.0)
  );
}
`

const installHeightColorShader = (material, heightAssignment, cacheKey) => {
  material.onBeforeCompile = shader => {
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        '#include <common>\nvarying float vPointCloudHeight;'
      )
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>\n${heightAssignment}`
      )
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>\n${HEIGHT_COLOR_FRAGMENT_GLSL}`
      )
      .replace(
        '#include <color_fragment>',
        '#include <color_fragment>\ndiffuseColor.rgb = pointCloudHeightColor(vPointCloudHeight);'
      )
  }
  material.customProgramCacheKey = () => cacheKey
  material.userData.pointCloudHeightColor = true
  return material
}

export const createHeightColoredPointsMaterial = options => installHeightColorShader(
  new THREE.PointsMaterial({ ...options, vertexColors: false }),
  'vPointCloudHeight = position.z;',
  'pointcloud-height-points-v1'
)

export const createHeightColoredBoxesMaterial = options => installHeightColorShader(
  new THREE.MeshBasicMaterial({ ...options, vertexColors: false }),
  `#ifdef USE_INSTANCING
    vPointCloudHeight = instanceMatrix[3].z;
  #else
    vPointCloudHeight = position.z;
  #endif`,
  'pointcloud-height-boxes-v1'
)
