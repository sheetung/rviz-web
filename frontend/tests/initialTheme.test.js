import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/utils/initialTheme.js', import.meta.url), 'utf8')
  .replace(/^import .*$/m, '')
  .replaceAll('import.meta.env', 'env')
  .replace('export const initializeTheme', 'globalThis.initializeTheme')
for (const socket of ['/ws/ros1', '/ws/ros2']) {
  const calls = []
  const document = { documentElement: { dataset: {}, classList: { remove() {} } } }
  const context = vm.createContext({
    env: { ROS_WS_URL: socket },
    createApiBaseUrl: (...args) => { calls.push(args); return '/api/v1' },
    document,
    window: { location: { origin: 'http://localhost:3000' } },
    localStorage: { getItem: () => null, setItem() {} },
    AbortController, setTimeout, clearTimeout, console,
    fetch: async url => {
      assert.equal(url, '/api/v1/configs/default.rvizweb')
      return { ok: true, json: async () => ({ config: { appearance: { theme: 'light' } } }) }
    }
  })
  vm.runInContext(source, context)
  await context.initializeTheme()
  assert.equal(calls[0].length, 2, 'Theme configuration must not use legacy ROS socket routing')
  assert.equal(document.documentElement.dataset.theme, 'light')
}
