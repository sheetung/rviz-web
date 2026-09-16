/**
 * API 客户端服务
 * 提供与后端 API 的通信接口
 */

import axios from 'axios'
import { createApiBaseUrl } from '../utils/websocketUrl.js'

// 创建 axios 实例
const browserLocation = typeof window === 'undefined' ? null : window.location
const api = axios.create({
  baseURL: createApiBaseUrl(
    browserLocation,
    import.meta.env?.VITE_BACKEND_PUBLIC_URL
  ),
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API Error:', error?.message || 'Unknown error')
    
    return Promise.reject(error)
  }
)

export const appApi = {
  getVersion: () => api.get('/version'),
  getSystemStatus: () => api.get('/system/status')
}

/**
 * RVizWeb config file API
 */
export const configApi = {
  listConfigs: () => api.get('/configs'),
  getConfig: (name) => api.get(`/configs/${encodeURIComponent(name)}`),
  saveConfig: (name, config) => api.post(
    `/configs/${encodeURIComponent(name)}`,
    { name, config }
  ),
  deleteConfig: (name) => api.delete(`/configs/${encodeURIComponent(name)}`)
}

/**
 * RTSP camera video API
 */
export const videoApi = {
  getStatus: () => api.get('/video/status'),
  createSession: (sourceUrl) => api.post(
    '/video/sessions',
    { source_url: sourceUrl },
    { timeout: 35000 }
  ),
  deleteSession: (sessionId) => api.delete(`/video/sessions/${encodeURIComponent(sessionId)}`),
  getStreamUrl: (sessionId) => api.getUri({
    url: `/video/stream/${encodeURIComponent(sessionId)}`,
    params: { t: Date.now() }
  })
}

export default api
