<template>
  <section
    ref="overlayRef"
    class="rtsp-video-overlay"
    :class="{ 'is-ready': isReady }"
    :style="overlayStyle"
    tabindex="0"
    role="group"
    aria-label="RTSP 视频窗口"
    @pointerdown.stop
    @mousedown.stop
    @click.stop
  >
    <div class="video-content" @pointerdown="startDrag">
      <img
        v-if="frameUrl"
        :src="frameUrl"
        alt="RTSP 相机实时视频"
        draggable="false"
        @load="onFrameLoaded"
        @error="onFrameError"
      />
      <div v-else class="video-loading">正在读取视频流</div>
    </div>

    <button
      type="button"
      class="overlay-control resize-control"
      title="拖动调整视频大小"
      aria-label="调整视频大小"
      @pointerdown.stop="startResize"
    >
      <el-icon><FullScreen /></el-icon>
    </button>
    <button
      type="button"
      class="overlay-control close-control"
      title="关闭视频"
      aria-label="关闭视频"
      @pointerdown.stop
      @click.stop="$emit('close')"
    >
      <el-icon><Close /></el-icon>
    </button>
    <button
      type="button"
      class="overlay-control reconnect-control"
      title="重新连接"
      aria-label="重新连接"
      @pointerdown.stop
      @click.stop="$emit('reconnect')"
    >
      <el-icon><Refresh /></el-icon>
    </button>
    <button
      type="button"
      class="overlay-control settings-control"
      title="视频设置"
      aria-label="视频设置"
      @pointerdown.stop
      @click.stop="$emit('edit')"
    >
      <el-icon><Setting /></el-icon>
    </button>
  </section>
</template>

<script>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Close, FullScreen, Refresh, Setting } from '@element-plus/icons-vue'
import { createJpegFrameParser } from '../../utils/jpegFrameParser'
import { resizeFromTopLeft } from '../../utils/videoOverlayLayout'

const DEFAULT_WIDTH = 360
const DEFAULT_HEIGHT = 240
const MIN_WIDTH = 240
const MIN_HEIGHT = 160
const EDGE_GAP = 14
const FRAME_STALL_TIMEOUT_MS = 12000
const STREAM_RETRY_DELAY_MS = 800
const MAX_STREAM_RESTARTS = 3

export default {
  name: 'RtspVideoOverlay',
  components: { Close, FullScreen, Refresh, Setting },
  props: {
    streamUrl: {
      type: String,
      required: true
    },
    layoutConfig: {
      type: Object,
      default: () => ({})
    }
  },
  emits: ['close', 'edit', 'reconnect', 'ready', 'stream-error', 'layout-change'],
  setup(props, { emit, expose }) {
    const overlayRef = ref(null)
    const frameUrl = ref('')
    const x = ref(0)
    const y = ref(0)
    const width = ref(DEFAULT_WIDTH)
    const height = ref(DEFAULT_HEIGHT)
    const aspectRatio = ref(DEFAULT_WIDTH / DEFAULT_HEIGHT)
    const isReady = ref(false)
    let interaction = null
    let parentResizeObserver = null
    let streamController = null
    let streamToken = 0
    let stallTimer = null
    let retryTimer = null
    let restartAttempts = 0
    let lastFrameAt = 0
    let consecutiveDecodeErrors = 0
    let streamErrorReported = false
    let naturalRatioApplied = false
    let usesDefaultPosition = false

    const overlayStyle = computed(() => ({
      left: `${x.value}px`,
      top: `${y.value}px`,
      width: `${width.value}px`,
      height: `${height.value}px`
    }))

    const parentBounds = () => {
      const parent = overlayRef.value?.parentElement
      return {
        width: parent?.clientWidth || window.innerWidth,
        height: parent?.clientHeight || window.innerHeight
      }
    }

    const clampLayout = () => {
      const bounds = parentBounds()
      const minWidth = Math.min(MIN_WIDTH, bounds.width)
      const minHeight = Math.min(MIN_HEIGHT, bounds.height)
      width.value = Math.max(minWidth, Math.min(width.value, bounds.width))
      height.value = Math.max(minHeight, Math.min(height.value, bounds.height))
      x.value = Math.max(0, Math.min(x.value, bounds.width - width.value))
      y.value = Math.max(0, Math.min(y.value, bounds.height - height.value))
    }

    const placeAtBottomRight = () => {
      const bounds = parentBounds()
      width.value = Math.min(DEFAULT_WIDTH, Math.max(MIN_WIDTH, bounds.width - EDGE_GAP * 2))
      height.value = Math.min(DEFAULT_HEIGHT, Math.max(MIN_HEIGHT, bounds.height - EDGE_GAP * 2))
      x.value = bounds.width - width.value - EDGE_GAP
      y.value = bounds.height - height.value - EDGE_GAP
      clampLayout()
    }

    const getLayout = () => ({
      x: Math.round(x.value),
      y: Math.round(y.value),
      width: Math.round(width.value),
      height: Math.round(height.value)
    })

    const applyConfiguredLayout = (layout = {}) => {
      const configuredWidth = Number(layout.width)
      const configuredHeight = Number(layout.height)
      const configuredX = Number(layout.x)
      const configuredY = Number(layout.y)
      width.value = Number.isFinite(configuredWidth) ? configuredWidth : DEFAULT_WIDTH
      height.value = Number.isFinite(configuredHeight) ? configuredHeight : DEFAULT_HEIGHT
      if (width.value > 0 && height.value > 0) aspectRatio.value = width.value / height.value

      const hasConfiguredPosition = layout.x !== null && layout.x !== undefined
        && Number.isFinite(configuredX)
        && layout.y !== null && layout.y !== undefined
        && Number.isFinite(configuredY)
      usesDefaultPosition = !hasConfiguredPosition

      if (hasConfiguredPosition) {
        x.value = configuredX
        y.value = configuredY
        clampLayout()
      } else {
        placeAtBottomRight()
      }
    }

    const stopInteraction = () => {
      const layoutChanged = Boolean(interaction)
      interaction = null
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopInteraction)
      window.removeEventListener('pointercancel', stopInteraction)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      if (layoutChanged) emit('layout-change', getLayout())
    }

    const beginInteraction = (event, type) => {
      if (event.button !== 0) return
      event.preventDefault()
      interaction = {
        type,
        pointerX: event.clientX,
        pointerY: event.clientY,
        x: x.value,
        y: y.value,
        width: width.value,
        height: height.value,
        aspectRatio: aspectRatio.value
      }
      window.addEventListener('pointermove', handlePointerMove)
      window.addEventListener('pointerup', stopInteraction)
      window.addEventListener('pointercancel', stopInteraction)
      document.body.style.userSelect = 'none'
      document.body.style.cursor = type === 'drag' ? 'grabbing' : 'nwse-resize'
    }

    const startDrag = (event) => {
      if (event.target.closest('.overlay-control')) return
      beginInteraction(event, 'drag')
    }

    const startResize = (event) => {
      beginInteraction(event, 'resize')
    }

    function handlePointerMove(event) {
      if (!interaction) return
      event.preventDefault()
      const deltaX = event.clientX - interaction.pointerX
      const deltaY = event.clientY - interaction.pointerY

      if (interaction.type === 'drag') {
        x.value = interaction.x + deltaX
        y.value = interaction.y + deltaY
        clampLayout()
        return
      }

      const resized = resizeFromTopLeft({
        ...interaction,
        deltaX,
        deltaY,
        minWidth: MIN_WIDTH,
        minHeight: MIN_HEIGHT
      })
      x.value = resized.x
      y.value = resized.y
      width.value = resized.width
      height.value = resized.height
      clampLayout()
    }

    const revokeFrameUrl = (url) => {
      if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(url)
      }
    }

    const clearFrame = () => {
      const previousUrl = frameUrl.value
      frameUrl.value = ''
      revokeFrameUrl(previousUrl)
    }

    const publishFrame = (frame) => {
      const nextUrl = URL.createObjectURL(new Blob([frame], { type: 'image/jpeg' }))
      const previousUrl = frameUrl.value
      frameUrl.value = nextUrl
      if (previousUrl) window.setTimeout(() => revokeFrameUrl(previousUrl), 0)
    }

    const reportStreamError = (error) => {
      if (streamErrorReported) return
      streamErrorReported = true
      isReady.value = false
      console.error('RTSP MJPEG stream stopped:', error)
      emit('stream-error')
    }

    const stopCurrentStream = ({ clear = true } = {}) => {
      streamToken += 1
      streamController?.abort()
      streamController = null
      if (stallTimer) {
        window.clearInterval(stallTimer)
        stallTimer = null
      }
      if (clear) clearFrame()
    }

    const cancelRetry = () => {
      if (retryTimer) {
        window.clearTimeout(retryTimer)
        retryTimer = null
      }
    }

    const scheduleStreamRestart = (error) => {
      if (streamErrorReported || retryTimer) return
      stopCurrentStream({ clear: false })
      if (restartAttempts >= MAX_STREAM_RESTARTS) {
        reportStreamError(error)
        return
      }
      restartAttempts += 1
      retryTimer = window.setTimeout(() => {
        retryTimer = null
        runStream()
      }, STREAM_RETRY_DELAY_MS)
    }

    const runStream = async () => {
      const token = streamToken
      const controller = new AbortController()
      streamController = controller
      lastFrameAt = Date.now()

      const parser = createJpegFrameParser(publishFrame)
      stallTimer = window.setInterval(() => {
        if (token !== streamToken) return
        if (Date.now() - lastFrameAt > FRAME_STALL_TIMEOUT_MS) {
          scheduleStreamRestart(new Error('等待新视频帧超时'))
        }
      }, 1000)

      try {
        const response = await fetch(props.streamUrl, {
          signal: controller.signal,
          cache: 'no-store',
          credentials: 'same-origin'
        })
        if (!response.ok || !response.body) {
          throw new Error(`视频流请求失败 (${response.status})`)
        }

        const reader = response.body.getReader()
        while (token === streamToken) {
          const { done, value } = await reader.read()
          if (done) throw new Error('视频流连接已结束')
          parser.push(value)
        }
      } catch (error) {
        if (token !== streamToken || controller.signal.aborted) return
        scheduleStreamRestart(error)
      }
    }

    const startStream = () => {
      cancelRetry()
      restartAttempts = 0
      streamErrorReported = false
      naturalRatioApplied = false
      isReady.value = false
      stopCurrentStream()
      runStream()
    }

    const stopStream = () => {
      cancelRetry()
      stopCurrentStream()
    }

    const onFrameLoaded = (event) => {
      lastFrameAt = Date.now()
      restartAttempts = 0
      consecutiveDecodeErrors = 0
      if (!naturalRatioApplied && event.target.naturalWidth > 0 && event.target.naturalHeight > 0) {
        aspectRatio.value = event.target.naturalWidth / event.target.naturalHeight
        naturalRatioApplied = true
        height.value = width.value / aspectRatio.value
        if (usesDefaultPosition) {
          placeAtBottomRight()
        } else {
          clampLayout()
        }
        emit('layout-change', getLayout())
      }
      if (!isReady.value) {
        isReady.value = true
        emit('ready')
      }
    }

    const onFrameError = () => {
      consecutiveDecodeErrors += 1
      if (consecutiveDecodeErrors >= 3) {
        scheduleStreamRestart(new Error('浏览器连续无法解码视频帧'))
      }
    }

    onMounted(async () => {
      await nextTick()
      applyConfiguredLayout(props.layoutConfig)
      const parent = overlayRef.value?.parentElement
      if (parent && typeof ResizeObserver !== 'undefined') {
        parentResizeObserver = new ResizeObserver(clampLayout)
        parentResizeObserver.observe(parent)
      }
      startStream()
    })

    watch(
      () => props.streamUrl,
      () => startStream()
    )

    watch(
      () => props.layoutConfig,
      (layout) => applyConfiguredLayout(layout),
      { deep: true }
    )

    onBeforeUnmount(() => {
      stopInteraction()
      stopStream()
      parentResizeObserver?.disconnect()
    })

    expose({ getLayout })

    return {
      overlayRef,
      frameUrl,
      overlayStyle,
      isReady,
      startDrag,
      startResize,
      onFrameLoaded,
      onFrameError
    }
  }
}
</script>

<style scoped>
.rtsp-video-overlay {
  position: absolute;
  z-index: 20;
  min-width: 240px;
  min-height: 160px;
  display: flex;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  background: #050709;
  border: 1px solid transparent;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  outline: none;
  transition: opacity 0.16s ease, border-color 0.16s ease;
}

.rtsp-video-overlay.is-ready {
  opacity: 1;
  pointer-events: auto;
}

.rtsp-video-overlay:hover,
.rtsp-video-overlay:focus-within {
  border-color: rgba(255, 255, 255, 0.46);
}

.video-content {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
}

.video-content:active {
  cursor: grabbing;
}

.video-content img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  pointer-events: none;
  user-select: none;
}

.video-loading {
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
}

.overlay-control {
  position: absolute;
  z-index: 5;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.9);
  background: rgba(10, 13, 16, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  cursor: pointer;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: background 0.15s ease, opacity 0.15s ease;
}

.rtsp-video-overlay:hover .overlay-control,
.rtsp-video-overlay:focus-within .overlay-control {
  opacity: 0.88;
  visibility: visible;
  pointer-events: auto;
}

.overlay-control:hover,
.overlay-control:focus-visible {
  color: #fff;
  background: rgba(10, 13, 16, 0.94);
  opacity: 1;
}

.resize-control {
  top: 8px;
  left: 8px;
  cursor: nwse-resize;
}

.close-control {
  top: 8px;
  right: 8px;
}

.reconnect-control {
  bottom: 8px;
  left: 8px;
}

.settings-control {
  right: 8px;
  bottom: 8px;
}
@media (pointer: coarse) {
  .overlay-control { width: 32px; height: 32px; opacity: 0.88; visibility: visible; pointer-events: auto; }
}
</style>
