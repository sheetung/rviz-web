// Own one pointer per navigation gesture. Interrupted or multi-touch gestures
// must never finish a goal selection.
export const createNavigationPointer = ({ onStart, onMove, onEnd, onCancel, canFinish = () => true }) => {
  let activeId = null
  let captureTarget = null
  const release = () => {
    const id = activeId
    const target = captureTarget
    activeId = null
    captureTarget = null
    if (target?.hasPointerCapture?.(id)) target.releasePointerCapture(id)
  }
  const cancel = () => {
    if (activeId === null) return
    release()
    onCancel()
  }
  return {
    start(event) {
      if (activeId !== null) {
        if (event.pointerId !== activeId) cancel()
        return
      }
      if (!event.isPrimary || event.button !== 0) return
      if (onStart(event) === false) return
      activeId = event.pointerId
      captureTarget = event.currentTarget
      captureTarget?.setPointerCapture?.(activeId)
    },
    move(event) {
      if (event.pointerId === activeId) onMove(event)
    },
    end(event) {
      if (event.pointerId !== activeId) return
      release()
      if (canFinish(event)) onEnd(event)
      else onCancel()
    },
    cancel(event) {
      if (!event || event.pointerId === activeId) cancel()
    }
  }
}
