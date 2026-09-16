import { createApiBaseUrl } from './websocketUrl'

const normalizeConfigName = (name) => {
  const trimmed = (name || 'default.rvizweb').trim()
  return trimmed.endsWith('.rvizweb') ? trimmed : `${trimmed}.rvizweb`
}

const normalizeTheme = (theme) => theme === 'light' ? 'light' : 'dark'

export const initializeTheme = async () => {
  const configName = normalizeConfigName(import.meta.env.VITE_RVIZWEB_CONFIG)
  const browserLocation = typeof window === 'undefined' ? null : window.location
  const apiBaseUrl = createApiBaseUrl(
    browserLocation,
    import.meta.env.VITE_BACKEND_PUBLIC_URL
  )
  const cacheKey = `rvizweb-theme:${apiBaseUrl}:${configName}`
  const cachedTheme = localStorage.getItem(cacheKey)

  if (cachedTheme) {
    document.documentElement.dataset.theme = normalizeTheme(cachedTheme)
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 3000)

  try {
    const response = await fetch(
      `${apiBaseUrl}/configs/${encodeURIComponent(configName)}`,
      {
        signal: controller.signal,
        credentials: 'include'
      }
    )
    if (!response.ok) throw new Error(`Config request failed: ${response.status}`)
    const data = await response.json()
    const theme = normalizeTheme((data.config || data).appearance?.theme)
    document.documentElement.dataset.theme = theme
    localStorage.setItem(cacheKey, theme)
  } catch (error) {
    if (!cachedTheme) document.documentElement.dataset.theme = 'dark'
    console.warn('Failed to initialize theme from startup config:', error)
  } finally {
    clearTimeout(timeoutId)
    document.documentElement.classList.remove('theme-loading')
  }
}
