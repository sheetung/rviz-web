const POINT_FIELD_READERS = {
  1: (view, offset) => view.getInt8(offset),
  2: (view, offset) => view.getUint8(offset),
  3: (view, offset, littleEndian) => view.getInt16(offset, littleEndian),
  4: (view, offset, littleEndian) => view.getUint16(offset, littleEndian),
  5: (view, offset, littleEndian) => view.getInt32(offset, littleEndian),
  6: (view, offset, littleEndian) => view.getUint32(offset, littleEndian),
  7: (view, offset, littleEndian) => view.getFloat32(offset, littleEndian),
  8: (view, offset, littleEndian) => view.getFloat64(offset, littleEndian)
}

const POINT_FIELD_BYTES = {
  1: 1,
  2: 1,
  3: 2,
  4: 2,
  5: 4,
  6: 4,
  7: 4,
  8: 8
}

const normalizePointData = (message) => {
  if (message.data instanceof Uint8Array) return message.data
  if (ArrayBuffer.isView(message.data)) {
    return new Uint8Array(message.data.buffer, message.data.byteOffset, message.data.byteLength)
  }
  if (message.data instanceof ArrayBuffer) return new Uint8Array(message.data)
  if (Array.isArray(message.data)) return new Uint8Array(message.data)
  return new Uint8Array()
}

const pointField = (fields, name, fallbackOffset) => {
  const field = fields.find(candidate => candidate?.name === name)
  return {
    offset: Number(field?.offset ?? fallbackOffset),
    datatype: Number(field?.datatype ?? 7)
  }
}

const readField = (view, byteOffset, field, littleEndian) => {
  const reader = POINT_FIELD_READERS[field.datatype]
  if (!reader) return Number.NaN
  return reader(view, byteOffset + field.offset, littleEndian)
}

const validCoordinate = (value) => Number.isFinite(value) && Math.abs(value) < 1000

const normalizeSampleStep = (value) => {
  const numericValue = Number(value)
  return Math.max(1, Math.min(32, Number.isFinite(numericValue) ? Math.round(numericValue) : 1))
}

const emptyResult = (error, totalPoints = 0) => ({
  error,
  pointCount: 0,
  totalPoints,
  positions: new Float32Array(),
  bounds: null
})

const finalizeResult = (positions, pointCount, totalPoints, bounds) => ({
  error: '',
  pointCount,
  totalPoints,
  positions: positions.subarray(0, pointCount * 3),
  bounds
})

const decodeStructuredPoints = (points, sampleStep) => {
  const totalPoints = Math.min(points.length, 5000)
  const positions = new Float32Array(Math.ceil(totalPoints / sampleStep) * 3)
  const minimum = [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY]
  const maximum = [Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY]
  let pointCount = 0

  for (let index = 0; index < totalPoints; index += sampleStep) {
    const point = points[index]
    const x = Number(point?.x ?? 0)
    const y = Number(point?.y ?? 0)
    const z = Number(point?.z ?? 0)
    if (!validCoordinate(x) || !validCoordinate(y) || !validCoordinate(z)) continue

    const outputOffset = pointCount * 3
    positions[outputOffset] = x
    positions[outputOffset + 1] = y
    positions[outputOffset + 2] = z
    minimum[0] = Math.min(minimum[0], x)
    minimum[1] = Math.min(minimum[1], y)
    minimum[2] = Math.min(minimum[2], z)
    maximum[0] = Math.max(maximum[0], x)
    maximum[1] = Math.max(maximum[1], y)
    maximum[2] = Math.max(maximum[2], z)
    pointCount++
  }

  if (pointCount === 0) return emptyResult('点云为空或数据格式无效', totalPoints)
  return finalizeResult(positions, pointCount, totalPoints, { minimum, maximum })
}

const compactFloat32Layout = (message, fields, pointStep, rowStep, width, height, data) => {
  if (
    message.data_encoding !== 'pointcloud-binary-v1' ||
    message.is_bigendian === true ||
    pointStep !== 12 ||
    rowStep !== width * pointStep ||
    data.byteOffset % Float32Array.BYTES_PER_ELEMENT !== 0 ||
    data.byteLength < width * height * pointStep
  ) return false

  return ['x', 'y', 'z'].every((name, index) => {
    const field = fields.find(candidate => candidate?.name === name)
    return Number(field?.offset) === index * 4 &&
      Number(field?.datatype) === 7 &&
      Number(field?.count ?? 1) === 1
  })
}

const decodeCompactFloat32 = (data, totalPoints, sampleStep) => {
  const source = new Float32Array(data.buffer, data.byteOffset, totalPoints * 3)
  const minimum = [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY]
  const maximum = [Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY]

  if (sampleStep > 1) {
    const positions = new Float32Array(Math.ceil(totalPoints / sampleStep) * 3)
    let pointCount = 0
    for (let index = 0; index < totalPoints; index += sampleStep) {
      const sourceOffset = index * 3
      const x = source[sourceOffset]
      const y = source[sourceOffset + 1]
      const z = source[sourceOffset + 2]
      if (!validCoordinate(x) || !validCoordinate(y) || !validCoordinate(z)) continue
      const outputOffset = pointCount * 3
      positions[outputOffset] = x
      positions[outputOffset + 1] = y
      positions[outputOffset + 2] = z
      minimum[0] = Math.min(minimum[0], x)
      minimum[1] = Math.min(minimum[1], y)
      minimum[2] = Math.min(minimum[2], z)
      maximum[0] = Math.max(maximum[0], x)
      maximum[1] = Math.max(maximum[1], y)
      maximum[2] = Math.max(maximum[2], z)
      pointCount++
    }
    if (pointCount === 0) return emptyResult('点云为空或数据格式无效', totalPoints)
    return finalizeResult(positions, pointCount, totalPoints, { minimum, maximum })
  }

  let allCoordinatesValid = true

  for (let offset = 0; offset < source.length; offset += 3) {
    const x = source[offset]
    const y = source[offset + 1]
    const z = source[offset + 2]
    if (!validCoordinate(x) || !validCoordinate(y) || !validCoordinate(z)) {
      allCoordinatesValid = false
      continue
    }
    minimum[0] = Math.min(minimum[0], x)
    minimum[1] = Math.min(minimum[1], y)
    minimum[2] = Math.min(minimum[2], z)
    maximum[0] = Math.max(maximum[0], x)
    maximum[1] = Math.max(maximum[1], y)
    maximum[2] = Math.max(maximum[2], z)
  }

  if (allCoordinatesValid) {
    return finalizeResult(source, totalPoints, totalPoints, { minimum, maximum })
  }

  const positions = new Float32Array(totalPoints * 3)
  let pointCount = 0
  for (let offset = 0; offset < source.length; offset += 3) {
    const x = source[offset]
    const y = source[offset + 1]
    const z = source[offset + 2]
    if (!validCoordinate(x) || !validCoordinate(y) || !validCoordinate(z)) continue
    const outputOffset = pointCount * 3
    positions[outputOffset] = x
    positions[outputOffset + 1] = y
    positions[outputOffset + 2] = z
    pointCount++
  }
  if (pointCount === 0) return emptyResult('点云为空或数据格式无效', totalPoints)
  return finalizeResult(positions, pointCount, totalPoints, { minimum, maximum })
}

export const decodePointCloudMessage = (message, options = {}) => {
  const sampleStep = normalizeSampleStep(options.sampleStep)
  if (!message || typeof message !== 'object') return emptyResult('点云消息为空')
  if (message.error) return emptyResult(String(message.error))
  if (Array.isArray(message.points)) return decodeStructuredPoints(message.points, sampleStep)
  if (!Array.isArray(message.fields) || message.data === undefined) {
    return emptyResult('点云缺少 fields 或 data')
  }

  const width = Math.max(0, Number(message.width) || 0)
  const height = Math.max(0, Number(message.height) || 0)
  const totalPoints = width * height
  const pointStep = Math.max(1, Number(message.point_step) || 16)
  const rowStep = Math.max(pointStep * width, Number(message.row_step) || 0)
  if (totalPoints === 0) return emptyResult('点云为空或数据格式无效')

  const data = normalizePointData(message)
  if (data.byteLength === 0) return emptyResult('点云数据为空', totalPoints)

  if (compactFloat32Layout(message, message.fields, pointStep, rowStep, width, height, data)) {
    return decodeCompactFloat32(data, totalPoints, sampleStep)
  }

  const xField = pointField(message.fields, 'x', 0)
  const yField = pointField(message.fields, 'y', 4)
  const zField = pointField(message.fields, 'z', 8)
  const fields = [xField, yField, zField]
  const requiredBytes = Math.max(
    ...fields.map(field => field.offset + (POINT_FIELD_BYTES[field.datatype] || 0))
  )
  if (requiredBytes <= 0 || requiredBytes > pointStep) {
    return emptyResult('点云 XYZ 字段超出 point_step', totalPoints)
  }

  const positions = new Float32Array(Math.ceil(totalPoints / sampleStep) * 3)
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength)
  const littleEndian = message.is_bigendian !== true
  const hasRowPadding = message.sampled !== true && height > 1 && rowStep >= width * pointStep
  const minimum = [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY]
  const maximum = [Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY]
  let pointCount = 0

  for (let index = 0; index < totalPoints; index += sampleStep) {
    const row = Math.floor(index / width)
    const column = index % width
    const byteOffset = hasRowPadding ? row * rowStep + column * pointStep : index * pointStep
    if (byteOffset + requiredBytes > data.byteLength) break

    const x = readField(view, byteOffset, xField, littleEndian)
    const y = readField(view, byteOffset, yField, littleEndian)
    const z = readField(view, byteOffset, zField, littleEndian)
    if (!validCoordinate(x) || !validCoordinate(y) || !validCoordinate(z)) continue

    const outputOffset = pointCount * 3
    positions[outputOffset] = x
    positions[outputOffset + 1] = y
    positions[outputOffset + 2] = z
    minimum[0] = Math.min(minimum[0], x)
    minimum[1] = Math.min(minimum[1], y)
    minimum[2] = Math.min(minimum[2], z)
    maximum[0] = Math.max(maximum[0], x)
    maximum[1] = Math.max(maximum[1], y)
    maximum[2] = Math.max(maximum[2], z)
    pointCount++
  }

  if (pointCount === 0) return emptyResult('点云为空或数据格式无效', totalPoints)
  return finalizeResult(positions, pointCount, totalPoints, { minimum, maximum })
}
