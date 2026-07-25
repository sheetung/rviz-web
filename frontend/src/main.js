/**
 * Vue.js 应用入口
 * RViz Web 可视化系统
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/es/components/message/style/css'

import App from './App.vue'
import router from './router'
import { initializeTheme } from './utils/initialTheme'

await initializeTheme()
const app = createApp(App)

// 状态管理
app.use(createPinia())

// 路由
app.use(router)

app.mount('#app')
