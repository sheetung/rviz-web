import assert from 'node:assert/strict'
import test from 'node:test'
import { createNavigationPointer } from '../src/utils/navigationPointer.js'

const pointer = (pointerId, extra = {}) => ({ pointerId, isPrimary: true, button: 0, ...extra })
const setup = () => {
  const calls = []
  const gesture = createNavigationPointer({
    onStart: () => calls.push('start'),
    onMove: () => calls.push('move'),
    onEnd: () => calls.push('publish'),
    onCancel: () => calls.push('cancel')
  })
  return { calls, gesture }
}

test('mouse, pen and touch complete only their own pointer gesture', () => {
  for (const pointerType of ['mouse', 'pen', 'touch']) {
    const { calls, gesture } = setup()
    gesture.start(pointer(1, { pointerType }))
    gesture.move(pointer(2))
    gesture.end(pointer(2))
    gesture.move(pointer(1))
    gesture.end(pointer(1))
    gesture.cancel(pointer(1))
    assert.deepEqual(calls, ['start', 'move', 'publish'])
  }
})

test('a second finger cancels selection and neither release publishes', () => {
  const { calls, gesture } = setup()
  gesture.start(pointer(1))
  gesture.start(pointer(2, { isPrimary: false }))
  gesture.end(pointer(2))
  gesture.end(pointer(1))
  assert.deepEqual(calls, ['start', 'cancel'])
})

test('pointer cancellation, capture loss and tool changes discard selection', () => {
  for (const explicitEvent of [true, false]) {
    const { calls, gesture } = setup()
    gesture.start(pointer(1))
    gesture.cancel(explicitEvent ? pointer(1) : undefined)
    gesture.end(pointer(1))
    assert.deepEqual(calls, ['start', 'cancel'])
    gesture.start(pointer(3))
    gesture.end(pointer(3))
    assert.equal(calls.at(-1), 'publish')
  }
})

test('camera interactions and non-primary presses do not capture or publish', () => {
  const gesture = createNavigationPointer({
    onStart: () => false,
    onMove: () => assert.fail('unexpected move'),
    onEnd: () => assert.fail('unexpected publish'),
    onCancel: () => assert.fail('unexpected cancel')
  })
  gesture.start(pointer(1, { currentTarget: { setPointerCapture: () => assert.fail('unexpected capture') } }))
  gesture.move(pointer(1))
  gesture.end(pointer(1))
  const { calls, gesture: other } = setup()
  other.start(pointer(2, { isPrimary: false }))
  other.start(pointer(3, { button: 2 }))
  assert.deepEqual(calls, [])
})


test('releasing outside the scene cancels and releases pointer capture', () => {
  let captured = null
  const calls = []
  const currentTarget = {
    setPointerCapture: id => { captured = id },
    hasPointerCapture: id => captured === id,
    releasePointerCapture: () => { captured = null }
  }
  const gesture = createNavigationPointer({
    onStart: () => true,
    onMove: () => {},
    onEnd: () => assert.fail('must not publish outside the scene'),
    onCancel: () => calls.push('cancel'),
    canFinish: event => event.clientX >= 0 && event.clientX <= 500
  })
  gesture.start(pointer(1, { currentTarget }))
  assert.equal(captured, 1)
  gesture.end(pointer(1, { clientX: 510 }))
  assert.equal(captured, null)
  assert.deepEqual(calls, ['cancel'])
})
