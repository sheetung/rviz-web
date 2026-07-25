import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createHeightColoredBoxesMaterial,
  createHeightColoredPointsMaterial
} from '../src/utils/pointCloudMaterial.js'

const compileShader = material => {
  const shader = {
    vertexShader: '#include <common>\n#include <begin_vertex>',
    fragmentShader: '#include <common>\n#include <color_fragment>'
  }
  material.onBeforeCompile(shader)
  return shader
}

test('point material computes height color in the GPU shader', () => {
  const material = createHeightColoredPointsMaterial({ size: 2 })
  const shader = compileShader(material)

  assert.equal(material.vertexColors, false)
  assert.match(shader.vertexShader, /vPointCloudHeight = position\.z/)
  assert.match(shader.fragmentShader, /pointCloudHeightColor/)
  assert.match(shader.fragmentShader, /diffuseColor\.rgb/)
})

test('box material colors instances from their translated height', () => {
  const material = createHeightColoredBoxesMaterial({ color: 0xffffff })
  const shader = compileShader(material)

  assert.match(shader.vertexShader, /instanceMatrix\[3\]\.z/)
  assert.match(shader.fragmentShader, /pointCloudHeightColor/)
})
