const browserBaseUrl = (location) => {
  if (location?.origin) return location.origin
  const protocol = location?.protocol || 'http:'
  const authority = location?.host || location?.hostname || 'localhost'
  return `${protocol}//${authority}`
}

export const createApiBaseUrl = (location, explicitBackendUrl = '', explicitWebSocketUrl = '') => {
  if (String(explicitWebSocketUrl || '').trim()) {
    const socket = new URL(createWebSocketUrl(location, explicitWebSocketUrl))
    const match = socket.pathname.match(/^(.*)\/ws(?:\/(ros[12]))?$/)
    if (!match) throw new Error('ROS_WS_URL must end in /ws, /ws/ros1 or /ws/ros2')
    socket.protocol = socket.protocol === 'wss:' ? 'https:' : 'http:'
    const base = `${match[1]}${match[2] ? `/${match[2]}` : ''}`
    socket.pathname = `${base}/api/v1`
    socket.search = ''
    if (explicitBackendUrl && createApiBaseUrl(location, explicitBackendUrl) !== socket.toString()) {
      throw new Error('VITE_BACKEND_PUBLIC_URL conflicts with ROS_WS_URL')
    }
    return socket.toString()
  }
  const explicit = String(explicitBackendUrl || '').trim()
  if (!explicit) return '/api/v1'

  const url = new URL(explicit, browserBaseUrl(location))
  if (url.protocol === 'ws:') url.protocol = 'http:'
  if (url.protocol === 'wss:') url.protocol = 'https:'
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/v1`
  url.search = ''
  url.hash = ''
  return url.toString().replace(/\/$/, '')
}

export const createWebSocketUrl = (location, explicitWebSocketUrl = '') => {
  const protocol = location?.protocol === 'https:' ? 'wss:' : 'ws:'
  const hostname = location?.hostname || 'localhost'
  const sameOriginAuthority = location?.host || hostname
  const explicitSocket = String(explicitWebSocketUrl || '').trim()

  if (explicitSocket) {
    const url = new URL(explicitSocket, `${protocol}//${sameOriginAuthority}`)
    if (!['ws:', 'wss:', 'http:', 'https:'].includes(url.protocol)) throw new Error('Invalid WebSocket protocol')
    url.protocol = url.protocol === 'https:' || url.protocol === 'wss:' ? 'wss:' : 'ws:'
    if (location?.protocol === 'https:' && url.protocol !== 'wss:') throw new Error('HTTPS requires wss')
    url.hash = ''
    return url.toString()
  }

  return `${protocol}//${sameOriginAuthority}/ws`
}
