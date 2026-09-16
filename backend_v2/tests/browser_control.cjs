// Controls go only to the isolated control_fixture supplied by the test runner.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const assert = require('node:assert/strict')
const url = process.argv[2] || 'http://127.0.0.1:18416'
const capture = process.env.CONTROL_CAPTURE
const binary = process.env.NATIVE_BINARY
const port = process.env.NATIVE_PORT || '18414'
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
let native
const start = () => { native = spawn(binary, ['--port', port], { stdio: 'ignore' }); return native }
const stop = async () => {
  if (!native || native.exitCode !== null) return
  const child = native
  const exited = new Promise(resolve => child.once('exit', resolve))
  child.kill('SIGTERM'); await exited
}
const events = () => fs.readFileSync(capture, 'utf8').split('\n').filter(line => line.startsWith('{')).map(JSON.parse)
const messages = topic => events().filter(event => event.topic === topic)
const waitFor = async predicate => {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await delay(100) }
  throw Error('Receiver condition timed out')
}
;(async () => {
  assert.ok(capture && binary, 'Set CONTROL_CAPTURE and NATIVE_BINARY')
  start()
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true,
    args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(() => {
      window.__test = { sockets: [], samples: 0 }
      const Socket = window.WebSocket
      window.WebSocket = class extends Socket {
        constructor(...args) { super(...args); window.__test.sockets.push(this); this.addEventListener('message', e => {
          if (typeof e.data === 'string' && JSON.parse(e.data).topic === '/v2_test/scan') window.__test.samples++
        }) }
      }
    })
    const config = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../rvizweb_configs/default.rvizweb')))
    config.config.displays = [{ name: '/v2_test/scan', messageType: 'sensor_msgs/msg/LaserScan', visible: true, config: {} }]
    config.config.fixedFrame = 'map'
    config.config.goal = { topic: '/v3_test/goal', x: 1.25, y: -2.5, z: 3 }
    await page.route('**/api/v1/configs', r => r.fulfill({ json: ['default.rvizweb'] }))
    await page.route('**/api/v1/configs/*', r => r.fulfill({ json: config }))
    await page.route('**/api/v1/version', r => r.fulfill({ json: { version: 'stage3-test' } }))
    await page.goto(url)
    await page.waitForFunction(() => window.__test.samples > 2)
    await page.getByText('位姿 / 目标', { exact: true }).click()
    await page.getByRole('button', { name: '发布', exact: true }).click()
    await waitFor(() => messages('/v3_test/goal').length === 1)
    assert.deepEqual(messages('/v3_test/goal')[0].msg.pose.position, { x: 1.25, y: -2.5, z: 3 })
    assert.equal(messages('/v3_test/goal')[0].msg.header.frame_id, 'map')
    await page.getByTitle('2D 初始位姿', { exact: true }).click()
    const box = await page.locator('.scene3d-container').boundingBox()
    await page.mouse.move(box.x + box.width*.45, box.y + box.height*.55)
    await page.mouse.down(); await page.mouse.move(box.x + box.width*.55, box.y + box.height*.55, { steps: 8 }); await page.mouse.up()
    await waitFor(() => messages('/initialpose').length === 1)
    assert.equal(messages('/initialpose')[0].msg.pose.covariance.length, 36)
    assert.equal(messages('/initialpose')[0].msg.pose.covariance[0], .25)
    const before = await page.evaluate(() => window.__test.samples)
    await stop()
    await page.waitForFunction(() => !document.querySelector('.connection-status').innerText.includes('已连接'))
    start()
    await page.waitForFunction(n => window.__test.samples > n + 2 && document.querySelector('.connection-status').innerText.includes('已连接'), before, { timeout: 20000 })
    assert.equal(messages('/v3_test/goal').length, 1, 'goal replayed after restart')
    assert.equal(messages('/initialpose').length, 1, 'initial pose replayed after restart')
    // The explicit UI reconnect action must also preserve display subscriptions.
    await page.locator('.connection-status .connection-badge button').click()
    const manualBefore = await page.evaluate(() => window.__test.samples)
    await page.getByRole('button', { name: '重连', exact: true }).click()
    await page.waitForFunction(n => window.__test.samples > n + 2, manualBefore, { timeout: 20000 })
    assert.equal(messages('/v3_test/goal').length, 1)
    assert.equal(messages('/initialpose').length, 1)
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ goal: messages('/v3_test/goal')[0].msg, initialPose: messages('/initialpose')[0].msg,
      recovery: await page.evaluate(() => ({ samples: window.__test.samples, connections: window.__test.sockets.length })) }))
    await page.screenshot({ path: process.argv[3] || '/tmp/stage3-browser.png' })
  } finally { await browser.close(); await stop() }
})().catch(async error => { console.error(error); await stop(); process.exit(1) })
