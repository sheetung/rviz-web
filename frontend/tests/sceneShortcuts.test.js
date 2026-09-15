import assert from 'node:assert/strict'
import { shouldHandleSceneShortcut } from '../src/utils/sceneShortcuts.js'

assert.equal(shouldHandleSceneShortcut({ key: 'm' }, false, false), true)
assert.equal(shouldHandleSceneShortcut({ key: 'M' }, false, false), true)
assert.equal(shouldHandleSceneShortcut({ key: 'g' }, false, false), false)
assert.equal(shouldHandleSceneShortcut({ key: 'g' }, true, false), true)
assert.equal(shouldHandleSceneShortcut({ key: 'Escape' }, false, true), true)
for (const flag of ['ctrlKey', 'metaKey', 'altKey', 'isComposing', 'defaultPrevented']) {
  assert.equal(shouldHandleSceneShortcut({ key: 'm', [flag]: true }, true, true), false)
}
for (const target of [{ isContentEditable: true }, { closest: () => ({}) }]) {
  assert.equal(shouldHandleSceneShortcut({ key: 'm', target }, true, true), false)
}
