const enabled = false

export const debugLog = (...args) => {
  if (enabled) console.debug(...args)
}

export const debugWarn = (...args) => {
  if (enabled) console.warn(...args)
}
