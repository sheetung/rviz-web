/**
 * API 客户端服务
 * 提供与后端 API 的通信接口
 */

import axios from 'axios'
import { createApiBaseUrl } from '../utils/websocketUrl'

// 创建 axios 实例
const browserLocation = typeof window === 'undefined' ? null : window.location
const api = axios.create({
  baseURL: createApiBaseUrl(
    browserLocation,
    import.meta.env.VITE_BACKEND_PUBLIC_URL
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

/**
 * ROS API 接口
 */
export const rosApi = {
  // 获取主题列表
  getTopics: () => api.get('/topics'),
  
  // 获取特定主题信息
  getTopicInfo: (topicName) => api.get('/topic-info', { params: { topic_name: topicName } }),
  
  // 订阅主题
  subscribeTopic: (topicName, messageType) => api.post('/topics/subscribe', {
    topic: topicName,
    message_type: messageType
  }),
  
  // 取消订阅主题
  unsubscribeTopic: (topicName) => api.post('/topics/unsubscribe', {
    topic: topicName
  }),
  
  // 发布消息到主题
  publishMessage: (topicName, messageType, message) => api.post('/topics/publish', {
    topic: topicName,
    message_type: messageType,
    msg: message
  }),
  
  // 获取主题频率
  getTopicFrequencies: () => api.get('/topics/frequencies'),
  
  // 获取节点列表
  getNodes: () => api.get('/nodes'),
  
  // 获取特定节点信息
  getNodeInfo: (nodeName) => api.get(`/nodes/${encodeURIComponent(nodeName)}`),
  
  // 获取系统状态
  getSystemStatus: () => api.get('/status')
}

export const appApi = {
  getVersion: () => api.get('/version')
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
