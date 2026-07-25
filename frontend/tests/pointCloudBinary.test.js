import assert from 'node:assert/strict'
import test from 'node:test'

import {
  decodePointCloudBinaryFrame,
  POINTCLOUD_BINARY_TRANSPORT
} from '../src/utils/pointCloudBinary.js'

const encodeFrame = (metadata, payload) => {
  const metadataBytes = new TextEncoder().encode(JSON.stringify(metadata))
  const payloadOffset = (12 + metadataBytes.length + 3) & ~3
  const frame = new ArrayBuffer(payloadOffset + payload.length)
  const bytes = new Uint8Array(frame)
  bytes.set([0x52, 0x56, 0x50, 0x43], 0)
  const view = new DataView(frame)
  view.setUint8(4, 1)
  view.setUint32(8, metadataBytes.length, true)
  bytes.set(metadataBytes, 12)
  bytes.set(payload, payloadOffset)
  return { frame, payloadOffset }
}

test('decodes aligned pointcloud-binary-v1 WebSocket frames', () => {
  const metadata = {
    op: 'publish',
    topic: '/points',
    msg: { width: 1, height: 1, data_encoding: POINTCLOUD_BINARY_TRANSPORT }
  }
  const payload = new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
  const { frame, payloadOffset } = encodeFrame(metadata, payload)

  const message = decodePointCloudBinaryFrame(frame)

  assert.equal(message.topic, '/points')
  assert.equal(message.msg.data_encoding, POINTCLOUD_BINARY_TRANSPORT)
  assert.equal(message.msg.data.buffer, frame)
  assert.equal(message.msg.data.byteOffset, payloadOffset)
  assert.deepEqual([...message.msg.data], [...payload])
})

test('rejects unrelated binary WebSocket frames', () => {
  assert.throws(
    () => decodePointCloudBinaryFrame(new Uint8Array(12)),
    /未知的 WebSocket 二进制帧/
  )
})
