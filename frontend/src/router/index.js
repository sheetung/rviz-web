/**
 * Vue Router 配置
 */

import { createRouter, createWebHistory } from 'vue-router'

const appTitle = String(import.meta.env.VITE_APP_TITLE || 'RVizWeb').trim() || 'RVizWeb'

const routes = [
  {
    path: '/',
    name: 'MainLayout',
    component: () => import('../components/layout/MainLayout.vue'),
    meta: { title: 'RViz Web 可视化系统' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - ${appTitle}`
  } else {
    document.title = appTitle
  }
  next()
})

export default router
