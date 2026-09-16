const ROS_MESSAGE_TYPE_PATTERN = /^[A-Za-z][A-Za-z0-9_]*\/(?:msg\/)?[A-Za-z][A-Za-z0-9_]*$/

// 这些消息通常携带大块二进制或结构化可视化数据，不适合自动扫描字段。
const DYNAMIC_FIELD_DISCOVERY_EXCLUSIONS = new Set([
  'sensor_msgs/msg/Image',
  'sensor_msgs/msg/CompressedImage',
  'sensor_msgs/msg/PointCloud',
  'sensor_msgs/msg/PointCloud2',
  'nav_msgs/msg/OccupancyGrid',
  'tf2_msgs/msg/TFMessage',
  'visualization_msgs/msg/Marker',
  'visualization_msgs/msg/MarkerArray'
])

const normalizeMessageType = (messageType = '') => {
  const parts = String(messageType).trim().split('/').filter(Boolean)
  if (parts.length === 2) return `${parts[0]}/msg/${parts[1]}`
  return parts.join('/')
}

export const supportsDynamicChartFields = (messageType = '') => {
  const normalized = normalizeMessageType(messageType)
  return ROS_MESSAGE_TYPE_PATTERN.test(normalized) &&
    !DYNAMIC_FIELD_DISCOVERY_EXCLUSIONS.has(normalized)
}

export const getTopicFrequencyState = (rawFrequency) => {
  if (rawFrequency === null || rawFrequency === undefined || rawFrequency === '') {
    return { frequency: null, isActive: false, status: '未测量' }
  }

  const frequency = Number(rawFrequency)
  if (!Number.isFinite(frequency) || frequency < 0) {
    return { frequency: null, isActive: false, status: '未测量' }
  }
  if (frequency === 0) {
    return { frequency: 0, isActive: false, status: '无数据' }
  }

  return {
    frequency,
    isActive: true,
    status: `${frequency.toFixed(1)} Hz`
  }
}

export const getYAxisLabelPrecision = (ticks = [], minPrecision = 1, maxPrecision = 4) => {
  const values = ticks
    .map(tick => typeof tick === 'number' ? tick : tick?.value)
    .filter(Number.isFinite)
  const steps = values
    .slice(1)
    .map((value, index) => Math.abs(value - values[index]))
    .filter(step => step > 0)

  if (steps.length === 0) return minPrecision

  const smallestStep = Math.min(...steps)
  const requiredPrecision = Math.ceil(-Math.log10(smallestStep) - 1e-10)
  return Math.min(maxPrecision, Math.max(minPrecision, requiredPrecision))
}

export const formatYAxisTick = (value, ticks = []) => {
  if (!Number.isFinite(value)) return ''

  const precision = getYAxisLabelPrecision(ticks)
  const zeroThreshold = 0.5 * (10 ** -precision)
  const normalizedValue = Math.abs(value) < zeroThreshold ? 0 : value
  return normalizedValue.toFixed(precision)
}

const numericFieldType = (value) => {
  if (!Number.isInteger(value)) return 'float64'
  if (value >= 0) return value <= 0xffffffff ? 'uint32' : 'uint64'
  return value >= -0x80000000 ? 'int32' : 'int64'
}

export const parseNumericMessageFields = (
  message,
  prefix = '',
  maxDepth = 3,
  currentDepth = 0
) => {
  const fields = []
  if (currentDepth >= maxDepth || !message || typeof message !== 'object') {
    return fields
  }

  for (const [key, value] of Object.entries(message)) {
    const fieldPath = prefix ? `${prefix}.${key}` : key
    const fieldName = key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' ')

    if (typeof value === 'number' && Number.isFinite(value)) {
      fields.push({
        name: fieldName,
        path: fieldPath,
        type: numericFieldType(value)
      })
    } else if (typeof value === 'boolean') {
      fields.push({ name: fieldName, path: fieldPath, type: 'bool' })
    } else if (Array.isArray(value)) {
      const hasNumericValues = value.some(
        item => typeof item === 'number' && Number.isFinite(item)
      )
      if (hasNumericValues) {
        fields.push(
          { name: `${fieldName} (Min)`, path: `${fieldPath}_computed_min`, type: 'computed' },
          { name: `${fieldName} (Max)`, path: `${fieldPath}_computed_max`, type: 'computed' },
          { name: `${fieldName} (Avg)`, path: `${fieldPath}_computed_avg`, type: 'computed' }
        )
      }
    } else if (value && typeof value === 'object') {
      fields.push(
        ...parseNumericMessageFields(
          value,
          fieldPath,
          maxDepth,
          currentDepth + 1
        )
      )
    }
  }

  return fields
}

// Resolve arrays before converting ordinary fields to scalar chart values.
export const extractChartFieldValue = (message, fieldPath) => {
  const resolve = path => path.split('.').reduce((value, key) => value?.[key], message)
  const range = /^_computed_(min|max|avg)_range$/.exec(fieldPath)
  const aggregate = /^(.*)_computed_(min|max|avg)$/.exec(fieldPath)
  if (range || aggregate) {
    const values = range ? message.ranges : resolve(aggregate[1])
    if (!Array.isArray(values)) return null
    const numbers = values.filter(value => Number.isFinite(value) && (!range ||
      (value >= (message.range_min ?? 0) && value <= (message.range_max ?? Infinity))))
    if (!numbers.length) return null
    const operation = range ? range[1] : aggregate[2]
    if (operation === 'min') return numbers.reduce((a, b) => Math.min(a, b))
    if (operation === 'max') return numbers.reduce((a, b) => Math.max(a, b))
    return numbers.reduce((a, b) => a + b, 0) / numbers.length
  }
  const value = resolve(fieldPath)
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'boolean') return value ? 1 : 0
  if (Array.isArray(value) || typeof value === 'string') return value.length
  return value && typeof value === 'object' ? Object.keys(value).length : null
}
