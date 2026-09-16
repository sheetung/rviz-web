// Run against an isolated Vite preview + display_fixture. Does not change saved configs.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs')
const assert = require('node:assert/strict')
const path = require('node:path')
;(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true,
    args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    await page.addInitScript(() => {
      window.__displayTest = { topics: {}, draws: 0 }
      const Socket = window.WebSocket
      window.WebSocket = class extends Socket {
        constructor(...args) { super(...args); this.addEventListener('message', e => {
          if (typeof e.data === 'string') { const m = JSON.parse(e.data); if (m.topic) window.__displayTest.topics[m.topic] = m }
        }) }
      }
      for (const klass of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
        for (const method of ['drawArrays', 'drawElements']) {
          const original = klass.prototype[method]
          klass.prototype[method] = function (...args) { window.__displayTest.draws++; return original.apply(this, args) }
        }
      }
    })
    const config = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../rvizweb_configs/default.rvizweb')))
    config.config.fixedFrame = 'static_a'
    config.config.displays = [
      ['scan', 'sensor_msgs/msg/LaserScan'], ['path', 'nav_msgs/msg/Path'],
      ['map', 'nav_msgs/msg/OccupancyGrid'], ['marker', 'visualization_msgs/msg/Marker'],
      ['markers', 'visualization_msgs/msg/MarkerArray'],
    ].map(([name, messageType]) => ({ name: '/v2_test/' + name, messageType, visible: true, config: {} }))
    config.config.layout.collapsedPanels.chart = false
    await page.route('**/api/v1/configs', r => r.fulfill({ json: ['default.rvizweb'] }))
    await page.route('**/api/v1/configs/*', r => r.fulfill({ json: config }))
    await page.route('**/api/v1/version', r => r.fulfill({ json: { version: 'stage2-test' } }))
    await page.goto(process.argv[2] || 'http://127.0.0.1:18396')
    await page.waitForFunction(() => Object.keys(window.__displayTest.topics).length >= 7 && window.__displayTest.draws > 30)
    // Inspect the same public component methods used by the UI, without production hooks.
    await page.evaluate(async () => {
      const components = new Map()
      const visit = vnode => {
        if (!vnode || typeof vnode !== 'object') return
        if (vnode.component) {
          components.set(vnode.component.type.name || vnode.component.type.__name, vnode.component.proxy)
          visit(vnode.component.subTree)
        }
        if (Array.isArray(vnode.children)) vnode.children.forEach(visit)
        if (vnode.suspense) visit(vnode.suspense.activeBranch)
      }
      visit(document.querySelector('#app')._vnode)
      window.__scene = components.get('Scene3D')
      window.__chart = components.get('ChartPanel')
      if (!window.__scene || !window.__chart) throw Error('Component tree: ' + [...components.keys()])
      await window.__chart.loadTopics()
      const topic = window.__chart.availableTopics.find(t => t.value === '/v2_test/numbers')
      if (!topic) throw Error('Numeric topic not discovered')
      window.__chart.expandTopic(topic)
    })
    await page.waitForFunction(() => window.__chart.getTopicFields({ value: '/v2_test/numbers', messageType: 'std_msgs/msg/Float64MultiArray' }).some(f => f.path === 'data_computed_avg'))
    await page.evaluate(() => window.__chart.addDataSeries('/v2_test/numbers', { name: 'Mean', path: 'data_computed_avg', type: 'computed' }, 'std_msgs/msg/Float64MultiArray'))
    await page.waitForFunction(() => window.__chart.dataSeries[0]?.data?.length > 3)
    const result = await page.evaluate(() => ({ stats: window.__scene.getPerformanceStats(), draws: window.__displayTest.draws,
      topics: Object.keys(window.__displayTest.topics), chart: window.__chart.dataSeries[0].data.slice(-3), body: document.body.innerText }))
    assert.ok(result.stats.objects > 5, JSON.stringify(result.stats))
    assert.ok(!result.body.includes('缺少 map'), result.body)
    assert.deepEqual(errors, [])
    delete result.body
    console.log(JSON.stringify(result))
    await page.screenshot({ path: process.argv[3] || '/tmp/stage2-browser.png' })
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exit(1) })
