// Separate clicks from drags, including a drag that returns to its start point.
export const createSplitterGesture = ({ onResize, onToggle, threshold = 5 }) => {
  let active = null
  return {
    start(x, y) {
      active = { x, y, dragged: false }
    },
    move(x, y) {
      if (!active) return
      if (Math.hypot(x - active.x, y - active.y) >= threshold) active.dragged = true
      if (active.dragged) onResize(x - active.x)
    },
    end(x, y) {
      if (!active) return
      this.move(x, y)
      const toggle = !active.dragged
      active = null
      if (toggle) onToggle()
    },
    cancel() {
      active = null
    }
  }
}
