import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatYAxisTick,
  getTopicFrequencyState,
  getYAxisLabelPrecision,
  parseNumericMessageFields,
  supportsDynamicChartFields
} from '../src/utils/chartTopics.js'


test('does not report an unmeasured topic as having no data', () => {
  assert.deepEqual(getTopicFrequencyState(null), {
    frequency: null,
    isActive: false,
    status: '未测量'
  })
  assert.deepEqual(getTopicFrequencyState(0), {
    frequency: 0,
    isActive: false,
    status: '无数据'
  })
  assert.deepEqual(getTopicFrequencyState(12.34), {
    frequency: 12.34,
    isActive: true,
    status: '12.3 Hz'
  })
})


test('accepts PX4 custom messages for dynamic chart field discovery', () => {
  assert.equal(
    supportsDynamicChartFields('px4_msgs/msg/VehicleLocalPosition'),
    true
  )
  assert.equal(supportsDynamicChartFields('sensor_msgs/msg/Image'), false)
})


test('formats small Y-axis intervals without collapsing labels', () => {
  const hundredthTicks = [-0.15, -0.14, -0.13, -0.12]
  assert.equal(getYAxisLabelPrecision(hundredthTicks), 2)
  assert.deepEqual(
    hundredthTicks.map(value => formatYAxisTick(value, hundredthTicks)),
    ['-0.15', '-0.14', '-0.13', '-0.12']
  )

  const finerTicks = [-0.105, -0.1, -0.095]
  assert.equal(getYAxisLabelPrecision(finerTicks), 3)
  assert.equal(formatYAxisTick(-0.0001, hundredthTicks), '0.00')
})


test('discovers finite numeric fields in a PX4 local position message', () => {
  const fields = parseNumericMessageFields({
    timestamp: 1784695855641740,
    xy_valid: true,
    x: -0.0032550410833209753,
    y: 0.021456271409988403,
    z: 0.003593623172491789,
    delta_xy: [0.013063520193099976, -0.02457532286643982],
    ref_lat: null,
    vxy_max: null
  })

  const fieldPaths = fields.map(field => field.path)
  assert.ok(fieldPaths.includes('x'))
  assert.ok(fieldPaths.includes('y'))
  assert.ok(fieldPaths.includes('z'))
  assert.ok(fieldPaths.includes('xy_valid'))
  assert.ok(fieldPaths.includes('delta_xy_computed_avg'))
  assert.ok(!fieldPaths.includes('ref_lat'))
  assert.ok(!fieldPaths.includes('vxy_max'))
})


test('extracts nested array aggregates and ignores nonfinite samples', async () => {
  const { extractChartFieldValue } = await import('../src/utils/chartTopics.js')
  const message = { sensor: { values: [1.25, -2.5, 42, null, NaN, Infinity] }, valid: true }
  assert.equal(extractChartFieldValue(message, 'sensor.values_computed_min'), -2.5)
  assert.equal(extractChartFieldValue(message, 'sensor.values_computed_max'), 42)
  assert.equal(extractChartFieldValue(message, 'sensor.values_computed_avg'), 40.75 / 3)
  assert.equal(extractChartFieldValue({ data: [null, NaN] }, 'data_computed_avg'), null)
  assert.equal(extractChartFieldValue(message, 'valid'), 1)
  assert.equal(extractChartFieldValue({ ranges: [null, 0, 2, Infinity], range_min: 0, range_max: 5 }, '_computed_avg_range'), 1)
})
