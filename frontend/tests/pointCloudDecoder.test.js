import assert from 'node:assert/strict'
import test from 'node:test'

import { decodePointCloudMessage } from '../src/utils/pointCloudDecoder.js'

const pointCloudMessage = (points, overrides = {}) => {
  const pointStep = 16
  const data = new Uint8Array(points.length * pointStep)
  const view = new DataView(data.buffer)
  points.forEach(([x, y, z], index) => {
    const offset = index * pointStep
    view.setFloat32(offset, x, true)
    view.setFloat32(offset + 4, y, true)
    view.setFloat32(offset + 8, z, true)
  })
  return {
    width: points.length,
    height: 1,
    point_step: pointStep,
    row_step: points.length * pointStep,
    is_bigendian: false,
    fields: [
      { name: 'x', offset: 0, datatype: 7, count: 1 },
      { name: 'y', offset: 4, datatype: 7, count: 1 },
      { name: 'z', offset: 8, datatype: 7, count: 1 }
    ],
    data: Buffer.from(data).toString('base64'),
    data_encoding: 'base64',
    ...overrides
  }
}

test('decodes base64 PointCloud2 data into compact transferable arrays', () => {
  const result = decodePointCloudMessage(pointCloudMessage([
    [1, 2, -1],
    [3, 4, 2]
  ]))

  assert.equal(result.error, '')
  assert.equal(result.pointCount, 2)
  assert.equal(result.totalPoints, 2)
  assert.deepEqual([...result.positions], [1, 2, -1, 3, 4, 2])
  assert.deepEqual(result.bounds, {
    minimum: [1, 2, -1],
    maximum: [3, 4, 2]
  })
  assert.equal(result.colors.length, 6)
  result.colors.forEach(value => assert.ok(Number.isFinite(value)))
})

test('filters invalid coordinates without leaving gaps in output arrays', () => {
  const result = decodePointCloudMessage(pointCloudMessage([
    [1, 2, 3],
    [Number.NaN, 5, 6],
    [7, 8, 9]
  ]))

  assert.equal(result.pointCount, 2)
  assert.deepEqual([...result.positions], [1, 2, 3, 7, 8, 9])
})

test('honors organized point cloud row padding', () => {
  const pointStep = 12
  const rowStep = 32
  const data = new Uint8Array(rowStep * 2)
  const view = new DataView(data.buffer)
  const coordinates = [
    [1, 2, 3],
    [4, 5, 6],
    [7, 8, 9],
    [10, 11, 12]
  ]
  coordinates.forEach(([x, y, z], index) => {
    const row = Math.floor(index / 2)
    const column = index % 2
    const offset = row * rowStep + column * pointStep
    view.setFloat32(offset, x, true)
    view.setFloat32(offset + 4, y, true)
    view.setFloat32(offset + 8, z, true)
  })

  const result = decodePointCloudMessage(pointCloudMessage([], {
    width: 2,
    height: 2,
    point_step: pointStep,
    row_step: rowStep,
    data: Buffer.from(data).toString('base64')
  }))

  assert.equal(result.pointCount, 4)
  assert.deepEqual([...result.positions], coordinates.flat())
})

test('returns an explicit error for malformed point fields', () => {
  const result = decodePointCloudMessage(pointCloudMessage([[1, 2, 3]], {
    fields: [
      { name: 'x', offset: 20, datatype: 7 },
      { name: 'y', offset: 4, datatype: 7 },
      { name: 'z', offset: 8, datatype: 7 }
    ]
  }))

  assert.equal(result.pointCount, 0)
  assert.match(result.error, /point_step/)
})
