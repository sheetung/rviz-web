export const POINTCLOUD_BINARY_TRANSPORT = 'pointcloud-binary-v1'

const MAGIC = [0x52, 0x56, 0x50, 0x43] // RVPC
const VERSION = 1
const HEADER_SIZE = 12
const textDecoder = new TextDecoder()

const alignToFloat32 = value => (value + 3) & ~3

export const decodePointCloudBinaryFrame = value => {
  let buffer
  let byteOffset = 0
  let byteLength = 0

  if (value instanceof ArrayBuffer) {
    buffer = value
    byteLength = value.byteLength
  } else if (ArrayBuffer.isView(value)) {
    buffer = value.buffer
    byteOffset = value.byteOffset
    byteLength = value.byteLength
  } else {
    throw new TypeError('点云二进制帧必须是 ArrayBuffer')
  }

  if (byteLength < HEADER_SIZE) throw new Error('点云二进制帧头不完整')
  const bytes = new Uint8Array(buffer, byteOffset, byteLength)
  if (!MAGIC.every((expected, index) => bytes[index] === expected)) {
    throw new Error('未知的 WebSocket 二进制帧')
  }

  const view = new DataView(buffer, byteOffset, byteLength)
  const version = view.getUint8(4)
  if (version !== VERSION) throw new Error(`不支持的点云二进制协议版本: ${version}`)

  const metadataLength = view.getUint32(8, true)
  const metadataEnd = HEADER_SIZE + metadataLength
  const payloadOffset = alignToFloat32(metadataEnd)
  if (metadataEnd > byteLength || payloadOffset > byteLength) {
    throw new Error('点云二进制帧长度无效')
  }

  const metadataBytes = new Uint8Array(
    buffer,
    byteOffset + HEADER_SIZE,
    metadataLength
  )
  const message = JSON.parse(textDecoder.decode(metadataBytes))
  if (message?.op !== 'publish' || !message.msg || typeof message.msg !== 'object') {
    throw new Error('点云二进制帧元数据无效')
  }

  message.msg.data = new Uint8Array(
    buffer,
    byteOffset + payloadOffset,
    byteLength - payloadOffset
  )
  message.msg.data_encoding = POINTCLOUD_BINARY_TRANSPORT
  return message
}
