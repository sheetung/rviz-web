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
    data,
    data_encoding: 'binary',
    ...overrides
  }
}

test('decodes PointCloud2 bytes into a compact transferable position array', () => {
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
  assert.equal('colors' in result, false)
})

test('uses aligned binary XYZ data directly without copying valid points', () => {
  const frame = new ArrayBuffer(4 + 24)
  const source = new Float32Array(frame, 4, 6)
  source.set([1, 2, 3, 4, 5, 6])
  const message = pointCloudMessage([], {
    width: 2,
    height: 1,
    point_step: 12,
    row_step: 24,
    data: new Uint8Array(frame, 4, 24),
    data_encoding: 'pointcloud-binary-v1'
  })

  const result = decodePointCloudMessage(message)

  assert.equal(result.positions.buffer, frame)
  assert.equal(result.positions.byteOffset, 4)
  assert.deepEqual([...result.positions], [1, 2, 3, 4, 5, 6])
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

test('sparse decoding keeps every configured Nth point', () => {
  const points = Array.from({ length: 10 }, (_, index) => [index, index + 1, index + 2])
  const result = decodePointCloudMessage(pointCloudMessage(points), { sampleStep: 4 })

  assert.equal(result.pointCount, 3)
  assert.equal(result.totalPoints, 10)
  assert.deepEqual([...result.positions], [0, 1, 2, 4, 5, 6, 8, 9, 10])
  assert.deepEqual(result.bounds, {
    minimum: [0, 1, 2],
    maximum: [8, 9, 10]
  })
})

test('sparse decoding also applies to aligned binary XYZ transport', () => {
  const source = new Float32Array([
    0, 1, 2,
    3, 4, 5,
    6, 7, 8,
    9, 10, 11
  ])
  const message = pointCloudMessage([], {
    width: 4,
    height: 1,
    point_step: 12,
    row_step: 48,
    data: new Uint8Array(source.buffer),
    data_encoding: 'pointcloud-binary-v1'
  })

  const result = decodePointCloudMessage(message, { sampleStep: 2 })

  assert.equal(result.pointCount, 2)
  assert.equal(result.totalPoints, 4)
  assert.deepEqual([...result.positions], [0, 1, 2, 6, 7, 8])
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
    data
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
