/**
 * ROS2 连接状态管理 Composable
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { debugLog } from '../utils/debug.js'
import { createWebSocketUrl } from '../utils/websocketUrl.js'
import { systemMessage } from './useSystemMessage.js'
import { decodePointCloudBinaryFrame } from '../utils/pointCloudBinary.js'

export const useConnectionStore = defineStore('connection', () => {
  // 连接状态
  const isConnected = ref(false)
  const isConnecting = ref(false)
  const connectionError = ref(null)
  const connectionLatency = ref(null)
  const websocket = ref(null)
  let latencyTimer = null
  let latencyMeasurementInFlight = false
  let reconnectTimer = null
  let intentionalDisconnect = false
  let socketGeneration = 0
  
  // 默认经当前页面同源代理连接；仅在独立部署后端时设置公开 URL。
  const browserLocation = typeof window === 'undefined' ? null : window.location
  const wsUrl = ref(createWebSocketUrl(
    browserLocation,
    import.meta.env?.ROS_WS_URL
  ))
  const reconnectAttempts = ref(0)
  const reconnectInterval = ref(3000)
  
  // 订阅的主题
  const subscribedTopics = ref(new Set())
  const desiredSubscriptions = ref(new Map())
  const messageHandlers = ref(new Map())
  const subscriptionRequests = new Set()
  
  // API调用的Promise管理
  const pendingRequests = ref(new Map())
  let requestIdCounter = 0
  
  // 计算属性
  const connectionStatus = computed(() => {
    if (isConnecting.value) return 'connecting'
    if (isConnected.value) return 'connected'
    if (connectionError.value) return 'error'
    return 'disconnected'
  })
  
  const connectionStatusText = computed(() => {
    switch (connectionStatus.value) {
      case 'connecting':
        return '连接中...'
      case 'connected':
        return '已连接'
      case 'error':
        return `连接错误: ${connectionError.value}`
      default:
        return '未连接'
    }
  })
  
  // 初始化连接
  const initializeConnection = async () => {
    if (isConnected.value || isConnecting.value) {
      return
    }
    
    await connect()
  }
  
  // 连接 WebSocket
  const connect = async () => {
    if (isConnected.value || isConnecting.value) return
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    const generation = ++socketGeneration
    intentionalDisconnect = false

    try {
      isConnecting.value = true
      connectionError.value = null

      const socket = new WebSocket(wsUrl.value)
      socket.binaryType = 'arraybuffer'
      websocket.value = socket

      socket.onopen = () => {
        if (generation !== socketGeneration) {
          socket.close(1000, 'Superseded connection')
          return
        }
        isConnected.value = true
        isConnecting.value = false
        reconnectAttempts.value = 0
        subscribedTopics.value.clear()
        subscriptionRequests.clear()
        advertisedTopics.value.clear()
        startLatencyTracking()
        desiredSubscriptions.value.forEach(({ messageType }, topic) => {
          requestSubscription(topic, messageType)
        })
        debugLog('WebSocket connected')
        systemMessage.success('已连接到 ROS2 服务')
      }
      
      socket.onmessage = (event) => {
        try {
          const message = typeof event.data === 'string'
            ? JSON.parse(event.data)
            : decodePointCloudBinaryFrame(event.data)
          debugLog(`[ConnectionStore] 📨 收到消息:`, message)
          handleMessage(message)
        } catch (error) {
          console.error('[ConnectionStore] ❌ 解析消息失败:', error)
        }
      }
      
      socket.onclose = (event) => {
        if (generation !== socketGeneration) return
        isConnected.value = false
        isConnecting.value = false
        websocket.value = null
        subscribedTopics.value.clear()
        advertisedTopics.value.clear()
        stopLatencyTracking()
        clearPendingRequests()
        
        if (!intentionalDisconnect) {
          // 只要不是用户主动断开，就持续定时重连。服务端重启时也可能
          // 使用 1000 正常关闭码，因此不能按关闭码停止恢复连接。
          connectionError.value = `连接关闭 (${event.code})`
          console.warn('WebSocket closed unexpectedly:', event)
          attemptReconnect()
        } else {
          debugLog('WebSocket closed normally')
        }
      }
      
      socket.onerror = (error) => {
        if (generation !== socketGeneration) return
        isConnected.value = false
        isConnecting.value = false
        websocket.value = null
        subscribedTopics.value.clear()
        advertisedTopics.value.clear()
        stopLatencyTracking()
        clearPendingRequests()
        connectionError.value = '连接失败'
        console.error('WebSocket error:', error)
        attemptReconnect()
      }
      
    } catch (error) {
      isConnecting.value = false
      connectionError.value = error.message
      console.error('Failed to connect:', error)
      attemptReconnect()
    }
  }
  
  // 断开连接
  const disconnect = () => {
    intentionalDisconnect = true
    socketGeneration++
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    stopLatencyTracking()
    if (websocket.value) {
      websocket.value.close(1000, 'Normal closure')
      websocket.value = null
    }
    isConnected.value = false
    isConnecting.value = false
    reconnectAttempts.value = 0
    connectionError.value = null
    subscribedTopics.value.clear()
    subscriptionRequests.clear()
    desiredSubscriptions.value.clear()
    messageHandlers.value.clear()
    advertisedTopics.value.clear()  // 清理发布者声明
    clearPendingRequests()
  }
  
  // 重连逻辑
  const attemptReconnect = () => {
    if (intentionalDisconnect || reconnectTimer) return

    reconnectAttempts.value++
    if (reconnectAttempts.value === 1) {
      systemMessage.warning('连接已断开，正在自动重连')
    }
    debugLog(`Attempting to reconnect (${reconnectAttempts.value})`)
    
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, reconnectInterval.value)
  }
  
  // 发送消息
  const sendMessage = (message) => {
    if (
      !isConnected.value ||
      !websocket.value ||
      websocket.value.readyState !== WebSocket.OPEN
    ) {
      console.warn('WebSocket not connected')
      return false
    }
    
    try {
      websocket.value.send(JSON.stringify(message))
      return true
    } catch (error) {
      console.error('Failed to send message:', error)
      return false
    }
  }
  
  // 处理接收到的消息
  const handleMessage = (message) => {
    const { op, topic, id } = message
    
    debugLog(`[ConnectionStore] 🔀 处理消息 - 操作: ${op}, 主题: ${topic || 'N/A'}`)

    // 根据操作类型处理消息
    switch (op) {
      case 'publish':
        debugLog(`[ConnectionStore] 📢 发布消息到主题: ${topic}`)
        handleTopicMessage(topic, message.msg)
        break
      case 'get_topics_result':
        debugLog(`[ConnectionStore] 📋 收到主题列表，数量: ${(message.topics || []).length}`)
        resolveRequest(id, message.topics || [])
        break
      case 'get_nodes_result':
        debugLog(`[ConnectionStore] 🏢 收到节点列表，数量: ${(message.nodes || []).length}`)
        resolveRequest(id, message.nodes || [])
        break
      case 'get_topic_types_result':
        debugLog(`[ConnectionStore] 🏷️ 收到主题类型映射`)
        resolveRequest(id, message.topic_types || {})
        break
      case 'get_topic_frequencies_result':
        debugLog(`[ConnectionStore] 📊 收到主题频率信息`)
        resolveRequest(id, message.frequencies || {})
        break
      case 'get_system_status_result':
        resolveRequest(id, message.status || null)
        break
      case 'get_services_result':
        debugLog(`[ConnectionStore] 🔧 收到服务列表，数量: ${(message.services || []).length}`)
        resolveRequest(id, message.services || [])
        break
      case 'get_service_types_result':
        debugLog(`[ConnectionStore] 🔧 收到服务类型映射`)
        resolveRequest(id, message.service_types || {})
        break
      case 'get_params_result':
        debugLog(`[ConnectionStore] ⚙️ 收到参数列表，数量: ${(message.params || []).length}`)
        resolveRequest(id, message.params || [])
        break
      case 'pong':
        resolveRequest(id, true)
        break
      case 'subscribe_result':
      case 'unsubscribe_result':
      case 'advertise_result':
      case 'unadvertise_result':
      case 'publish_result':
        resolveRequest(id, message)
        break
      case 'error':
        console.error(`[ConnectionStore] ❌ 收到错误消息:`, message.error)
        rejectRequest(id, message.error || 'Unknown error')
        break
      default:
        console.warn(`[ConnectionStore] ⚠️ 未知的消息操作: ${op}`, message)
    }
  }
  
  // 生成请求ID
  const generateRequestId = () => {
    return `req_${++requestIdCounter}_${Date.now()}`
  }
  
  // 解决请求Promise
  const resolveRequest = (requestId, data) => {
    if (requestId && pendingRequests.value.has(requestId)) {
      const { resolve, timeoutId } = pendingRequests.value.get(requestId)
      clearTimeout(timeoutId)
      resolve(data)
      pendingRequests.value.delete(requestId)
    }
  }
  
  // 拒绝请求Promise
  const rejectRequest = (requestId, error) => {
    if (requestId && pendingRequests.value.has(requestId)) {
      const { reject, timeoutId } = pendingRequests.value.get(requestId)
      clearTimeout(timeoutId)
      reject(new Error(error))
      pendingRequests.value.delete(requestId)
    }
  }
  
  // 发送API请求并返回Promise
  const sendApiRequest = (operation, params = {}) => {
    return new Promise((resolve, reject) => {
      if (!isConnected.value) {
        reject(new Error('Not connected to ROS'))
        return
      }
      
      const requestId = generateRequestId()
      const message = {
        op: operation,
        id: requestId,
        ...params
      }
      
      // 设置超时
      const timeoutId = setTimeout(() => {
        if (pendingRequests.value.has(requestId)) {
          pendingRequests.value.delete(requestId)
          reject(new Error(`Request timeout: ${operation}`))
        }
      }, 10000) // 10秒超时

      // 存储 Promise 及其超时句柄
      pendingRequests.value.set(requestId, { resolve, reject, timeoutId })
      
      if (!sendMessage(message)) {
        clearTimeout(timeoutId)
        pendingRequests.value.delete(requestId)
        reject(new Error(`Failed to send message: ${operation}`))
      }
    })
  }

  const measureLatency = async () => {
    if (!isConnected.value || latencyMeasurementInFlight) return

    latencyMeasurementInFlight = true
    const startedAt = performance.now()
    try {
      await sendApiRequest('ping')
      connectionLatency.value = Math.max(0, Math.round(performance.now() - startedAt))
    } catch {
      connectionLatency.value = null
    } finally {
      latencyMeasurementInFlight = false
    }
  }

  const stopLatencyTracking = () => {
    if (latencyTimer) {
      clearInterval(latencyTimer)
      latencyTimer = null
    }
    latencyMeasurementInFlight = false
    connectionLatency.value = null
  }

  const startLatencyTracking = () => {
    stopLatencyTracking()
    measureLatency()
    latencyTimer = setInterval(measureLatency, 5000)
  }
  
  // 处理主题消息
  const handleTopicMessage = (topic, message) => {
    const handlers = messageHandlers.value.get(topic)

    // 减少详细日志输出，只保留关键信息
    debugLog(`[ConnectionStore] 🎯 处理主题消息: ${topic}`)

    if (handlers && handlers.size > 0) {
      let handlerIndex = 0
      handlers.forEach(handler => {
        try {
          handlerIndex++
          handler(message)
          // 只在出错时输出详细信息
        } catch (error) {
          console.error(`[ConnectionStore] - ❌ 处理器 #${handlerIndex} 执行失败:`, error)
          console.error(`[ConnectionStore] - 消息内容:`, message)
        }
      })
    } else {
      console.warn(`[ConnectionStore] ⚠️ 主题 ${topic} 没有注册处理器`)
      console.warn(`[ConnectionStore] - 所有已注册的处理器:`)
      messageHandlers.value.forEach((handlerSet, handlerTopic) => {
        console.warn(`  - ${handlerTopic}: ${handlerSet.size} handlers`)
      })
    }
  }
  
  // 清理待处理请求（连接关闭时）
  const clearPendingRequests = () => {
    pendingRequests.value.forEach(({ reject, timeoutId }) => {
      clearTimeout(timeoutId)
      reject(new Error('Connection closed'))
    })
    pendingRequests.value.clear()
  }
  
  // 订阅主题
  const requestSubscription = async (topic, messageType) => {
    if (
      !isConnected.value ||
      subscribedTopics.value.has(topic) ||
      subscriptionRequests.has(topic)
    ) return
    subscriptionRequests.add(topic)
    try {
      const result = await sendApiRequest('subscribe', {
        topic,
        type: messageType
      })
      if (!result?.success) throw new Error(`订阅 ${topic} 未被后端确认`)
      if (desiredSubscriptions.value.has(topic)) {
        subscribedTopics.value.add(topic)
      }
      debugLog(`[ConnectionStore] ✅ Subscribed to ${topic}`)
    } catch (error) {
      subscribedTopics.value.delete(topic)
      console.error(`[ConnectionStore] ❌ Failed to subscribe ${topic}:`, error)
      systemMessage.error(`订阅 ${topic} 失败: ${error.message}`)
    } finally {
      subscriptionRequests.delete(topic)
    }
  }

  const subscribeTopic = (topic, messageType, handler) => {
    debugLog(`[ConnectionStore] 🔔 subscribeTopic called: topic=${topic}, type=${messageType}, connected=${isConnected.value}`)

    // 添加消息处理器
    if (!messageHandlers.value.has(topic)) {
      messageHandlers.value.set(topic, new Set())
    }
    messageHandlers.value.get(topic).add(handler)
    desiredSubscriptions.value.set(topic, { messageType })
    debugLog(`[ConnectionStore] ✅ Added handler for ${topic}, total handlers: ${messageHandlers.value.get(topic).size}`)

    // 如果还没有订阅这个主题，发送订阅请求
    if (isConnected.value) requestSubscription(topic, messageType)
    return true
  }
  
  // 取消订阅主题
  const unsubscribeTopic = (topic, handler) => {
    // 移除消息处理器
    const handlers = messageHandlers.value.get(topic)
    if (handlers) {
      handlers.delete(handler)
      
      // 如果没有处理器了，取消订阅
      if (handlers.size === 0) {
        messageHandlers.value.delete(topic)
        desiredSubscriptions.value.delete(topic)
        subscribedTopics.value.delete(topic)
        
        if (isConnected.value) {
          sendApiRequest('unsubscribe', { topic }).catch(error => {
            console.error(`[ConnectionStore] ❌ Failed to unsubscribe ${topic}:`, error)
          })
          debugLog(`Unsubscribed from ${topic}`)
        }
      }
    }
  }
  
  // 已声明的发布者
  const advertisedTopics = ref(new Set())

  // 声明发布者
  const advertise = async (topic, messageType) => {
    if (!isConnected.value) {
      console.warn('Not connected to ROS')
      throw new Error('Not connected to ROS')
    }

    if (advertisedTopics.value.has(topic)) {
      debugLog(`[ConnectionStore] 话题 ${topic} 已经声明过发布者`)
      return true
    }

    const result = await sendApiRequest('advertise', {
      topic: topic,
      type: messageType
    })

    if (result?.success) {
      advertisedTopics.value.add(topic)
      debugLog(`[ConnectionStore] ✅ 成功声明发布者: ${topic}`)
      return true
    }
    throw new Error(`后端未确认发布者声明: ${topic}`)
  }

  // 取消声明发布者
  const unadvertise = async (topic) => {
    if (!isConnected.value) {
      return false
    }

    debugLog(`[ConnectionStore] 取消声明发布者: ${topic}`)
    const result = await sendApiRequest('unadvertise', { topic })
    if (result?.success) {
      advertisedTopics.value.delete(topic)
      debugLog(`[ConnectionStore] ✅ 成功取消声明发布者: ${topic}`)
    }
    return result
  }

  // 发布消息到主题
  const publishMessage = async (topic, messageType, message) => {
    if (!isConnected.value) {
      console.warn('[ConnectionStore] Not connected to ROS')
      throw new Error('Not connected to ROS')
    }

    const result = await sendApiRequest('publish', {
      topic: topic,
      type: messageType,
      msg: message
    })

    if (!result?.success) throw new Error(`后端未确认消息发布: ${topic}`)
    advertisedTopics.value.add(topic)
    return true
  }
  
  // ROS API 方法 - 返回Promise
  
  // 获取主题列表
  const getTopics = async () => {
    try {
      const topics = await sendApiRequest('get_topics')
      debugLog('获取到主题列表:', topics)
      return topics
    } catch (error) {
      console.error('获取主题列表失败:', error)
      return []
    }
  }
  
  // 获取节点列表
  const getNodes = async () => {
    try {
      const nodes = await sendApiRequest('get_nodes')
      debugLog('获取到节点列表:', nodes)
      return nodes
    } catch (error) {
      console.error('获取节点列表失败:', error)
      return []
    }
  }
  
  // 获取主题类型映射
  const getTopicTypes = async () => {
    try {
      const topicTypes = await sendApiRequest('get_topic_types')
      debugLog('获取到主题类型:', topicTypes)
      return topicTypes
    } catch (error) {
      console.error('获取主题类型失败:', error)
      return {}
    }
  }
  
  // 获取主题频率信息
  const getTopicFrequencies = async () => {
    try {
      const frequencies = await sendApiRequest('get_topic_frequencies')
      debugLog('获取到主题频率:', frequencies)
      return frequencies
    } catch (error) {
      console.error('获取主题频率失败:', error)
      return {}
    }
  }
  
  // 获取系统状态
  const getSystemStatus = async () => {
    try {
      return await sendApiRequest('get_system_status')
    } catch (error) {
      console.error('获取系统状态失败:', error)
      return null
    }
  }

  // 获取服务列表
  const getServices = async () => {
    try {
      const services = await sendApiRequest('get_services')
      debugLog('获取到服务列表:', services)
      return services
    } catch (error) {
      console.error('获取服务列表失败:', error)
      return []
    }
  }
  
  // 获取服务类型映射
  const getServiceTypes = async () => {
    try {
      const serviceTypes = await sendApiRequest('get_service_types')
      debugLog('获取到服务类型:', serviceTypes)
      return serviceTypes
    } catch (error) {
      console.error('获取服务类型失败:', error)
      return {}
    }
  }
  
  // 获取参数列表
  const getParams = async () => {
    try {
      const params = await sendApiRequest('get_params')
      debugLog('获取到参数列表:', params)
      return params
    } catch (error) {
      console.error('获取参数列表失败:', error)
      return []
    }
  }
  
  return {
    // 状态
    isConnected,
    isConnecting,
    connectionError,
    connectionLatency,
    connectionStatus,
    connectionStatusText,
    websocket,
    reconnectAttempts,
    subscribedTopics: computed(() => Array.from(subscribedTopics.value)),
    
    // 配置
    wsUrl,
    reconnectInterval,
    
    // 方法
    initializeConnection,
    connect,
    disconnect,
    sendMessage,
    subscribeTopic,
    unsubscribeTopic,
    advertise,
    unadvertise,
    publishMessage,
    
    // ROS API方法
    getTopics,
    getNodes,
    getTopicTypes,
    getTopicFrequencies,
    getSystemStatus,
    getServices,
    getServiceTypes,
    getParams
  }
})
