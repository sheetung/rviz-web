// Production UI metrics; hooks only exist in this test browser, not app sources.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs=require('node:fs'); const path=require('node:path')
const [url,target]=process.argv.slice(2)
;(async()=>{
 const glArgs=process.env.BROWSER_GL==='auto' ? ['--no-sandbox','--ignore-gpu-blocklist','--enable-unsafe-swiftshader'] : ['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,args:glArgs})
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1})
  const errors=[]; page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.addInitScript(()=>{
   const b=window.__bench={collect:false,frames:[],decodes:[],draws:[],updates:[],longTasks:[],renderer:null,lastDecoded:null,lastDrawn:null}
   const NativeSocket=window.WebSocket
   window.WebSocket=class extends NativeSocket {
    constructor(...args){super(...args);this.addEventListener('message',e=>{
     if(!(e.data instanceof ArrayBuffer)||!b.collect)return
     const v=new DataView(e.data);if(v.byteLength<12||v.getUint32(0,false)!==0x52565043)return
     const length=v.getUint32(8,true); const m=JSON.parse(new TextDecoder().decode(new Uint8Array(e.data,12,length))).msg
     const stamp=m.header.stamp.sec*1000+(m.header.stamp.nanosec||m.header.stamp.nsec||0)/1e6
     b.frames.push([Date.now(),v.byteLength,Date.now()-stamp])
    })}
   }
   const NativeWorker=window.Worker
   window.Worker=class extends NativeWorker {
    constructor(...args){super(...args);this.sent=new Map();this.addEventListener('message',e=>{
      const sent=this.sent.get(e.data?.generation);if(!sent)return
      this.sent.delete(e.data.generation)
      b.lastDecoded={stamp:sent.stamp,generation:e.data.generation,points:e.data.decoded?.pointCount}
      if(b.collect)b.decodes.push([Date.now(),performance.now()-sent.at,e.data.decoded?.pointCount,e.data.decoded?.error||null])
    })}
    postMessage(m,...args){if(m?.message?.header){const stamp=m.message.header.stamp;this.sent.set(m.generation,{at:performance.now(),stamp:stamp.sec*1000+(stamp.nanosec||stamp.nsec||0)/1e6})}return super.postMessage(m,...args)}
   }
   for(const klass of [window.WebGLRenderingContext,window.WebGL2RenderingContext]){
    if(!klass)continue
    const original=klass.prototype.drawArrays
    klass.prototype.drawArrays=function(mode,first,count){
     if(mode===this.POINTS){
      if(!b.renderer){const ext=this.getExtension('WEBGL_debug_renderer_info');b.renderer=ext?this.getParameter(ext.UNMASKED_RENDERER_WEBGL):this.getParameter(this.RENDERER)}
      if(b.collect){
       b.draws.push([Date.now(),count])
       if(b.lastDecoded&&b.lastDrawn!==b.lastDecoded.generation){b.lastDrawn=b.lastDecoded.generation;b.updates.push([Date.now(),Date.now()-b.lastDecoded.stamp,count])}
      }
     }
     return original.call(this,mode,first,count)
    }
   }
   new PerformanceObserver(list=>{if(b.collect)for(const e of list.getEntries())b.longTasks.push(e.duration)}).observe({type:'longtask',buffered:false})
  })
  const root=path.resolve(__dirname,'../..')
  const config=JSON.parse(fs.readFileSync(path.join(root,'rvizweb_configs/default.rvizweb')))
  config.config.displays=[{name:'/benchmark/map',messageType:'sensor_msgs/msg/PointCloud2',visible:true,config:{pointSize:.07,sampleStep:1}}]
  config.config.fixedFrame='map';config.config.followFrame='';config.config.position.odomTopic=''
  config.config.scene.camera={position:{x:35,y:-50,z:45},target:{x:0,y:4,z:0},up:{x:0,y:0,z:1},zoom:1,projection:'perspective'}
  config.config.layout.collapsedPanels.chart=true
  await page.route('**/api/v1/configs',r=>r.fulfill({json:['default.rvizweb']}))
  await page.route('**/api/v1/configs/*',r=>r.fulfill({json:config}))
  await page.route('**/api/v1/version',r=>r.fulfill({json:{version:'benchmark',middleware:'ros2',protocol_version:1}}))
  await page.goto(url)
  await page.waitForFunction(()=>window.__bench.lastDecoded?.points>0,{},{timeout:25000})
  await page.waitForTimeout(4000)
  const start=await page.evaluate(()=>{window.__bench.collect=true;return Date.now()/1000})
  fs.writeFileSync(path.join(target,'browser-ready.json'),JSON.stringify({start}))
  while(!fs.existsSync(path.join(target,'browser-stop')))await new Promise(r=>setTimeout(r,100))
  const metrics=await page.evaluate(()=>{window.__bench.collect=false;return {...window.__bench,end:Date.now()/1000}})
  fs.writeFileSync(path.join(target,'browser.json'),JSON.stringify({start,...metrics,errors}))
  await page.screenshot({path:path.join(target,'browser.png')})
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)})
