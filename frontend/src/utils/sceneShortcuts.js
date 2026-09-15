export const shouldHandleSceneShortcut = (event, sceneFocused, navigationActive) => {
  if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return false
  const target = event.target
  if (target?.isContentEditable || target?.closest?.('input, textarea, select, [role="textbox"]')) return false
  // M returns to camera controls even after interacting with another panel.
  return event.key?.toLowerCase() === 'm' || sceneFocused || navigationActive
}
