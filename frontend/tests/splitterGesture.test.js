import assert from 'node:assert/strict'
import { createSplitterGesture } from '../src/utils/splitterGesture.js'

let toggles = 0
const widths = []
const gesture = createSplitterGesture({
  onToggle: () => { toggles += 1 },
  onResize: delta => widths.push(delta)
})

// Click and touch jitter toggle, without resizing.
gesture.start(100, 20)
gesture.end(102, 21)
assert.equal(toggles, 1)
assert.deepEqual(widths, [])
gesture.start(100, 20)
gesture.end(100, 20)
assert.equal(toggles, 2)

// Chart divider uses Y as its resize axis and restores its previous height.
let chartVisible = true
let chartHeight = 300
const chart = createSplitterGesture({
  onToggle: () => { chartVisible = !chartVisible },
  onResize: deltaY => { if (chartVisible) chartHeight = 300 - deltaY }
})
chart.start(200, 100)
chart.end(170, 100)
assert.equal(chartHeight, 330)
assert.equal(chartVisible, true)
chart.start(170, 100)
chart.end(170, 100)
assert.equal(chartVisible, false)
chart.start(170, 100)
chart.end(170, 100)
assert.equal(chartVisible, true)
assert.equal(chartHeight, 330)

// A drag must not collapse the panel, even if it returns to its origin.
gesture.start(100, 20)
gesture.move(130, 20)
gesture.end(100, 20)
assert.equal(toggles, 2)
assert.deepEqual(widths, [30, 0])

// Final pointer position also counts when no move event was delivered.
gesture.start(100, 20)
gesture.end(110, 20)
assert.equal(toggles, 2)
assert.equal(widths.at(-1), 10)

// Pointer cancellation/lost capture never toggles and ignores later events.
gesture.start(100, 20)
gesture.cancel()
gesture.end(100, 20)
gesture.move(140, 20)
assert.equal(toggles, 2)
assert.equal(widths.at(-1), 10)

// A vertical swipe is not a click either.
gesture.start(100, 20)
gesture.end(100, 40)
assert.equal(toggles, 2)
