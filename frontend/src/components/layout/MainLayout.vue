<template>
  <div class="main-layout">
    <div class="main-content" :style="{ gridTemplateColumns: `${sceneWidth}% 10px minmax(320px, ${100 - sceneWidth}%)` }">
      <section class="scene-section">
        <div class="scene-panel">
          <div class="scene-header">
            <h3>点云视图</h3>
            <div class="scene-controls">
              <div class="tool-group">
                <el-button size="small" :type="activeSceneTool === 'move' ? 'primary' : 'default'" title="移动相机 (M)" @click="activateSceneTool('move')" class="tool-btn">
                  <el-icon :size="14"><VideoCamera /></el-icon>
                  <kbd>M</kbd>
                </el-button>
                <el-button size="small" :type="activeSceneTool === '2d_goal' ? 'primary' : 'default'" title="2D 目标 (G)" @click="activateSceneTool('2d_goal')" class="tool-btn">
                  <el-icon :size="14"><Flag /></el-icon>
                  <kbd>G</kbd>
                </el-button>
              </div>
              <span class="tool-separator"></span>
              <div class="tool-group view-tool-group">
                <el-button size="small" title="刷新点云 (R)" @click="refreshPointClouds" class="tool-btn joined-tool-first">
                  <el-icon :size="14"><Refresh /></el-icon>
                  <kbd>R</kbd>
                </el-button>
                <el-button size="small" @click="toggleGrid" :type="sceneShowGrid ? 'primary' : 'default'" class="tool-btn joined-tool-middle" title="切换网格">
                  <el-icon :size="14"><Grid /></el-icon>
                </el-button>
                <el-button size="small" @click="toggleAxes" :type="sceneShowAxes ? 'primary' : 'default'" class="tool-btn joined-tool-middle" title="切换坐标轴">
                  <el-icon :size="14"><Connection /></el-icon>
                </el-button>
                <el-dropdown trigger="click" @command="setSceneViewPreset">
                  <el-button size="small" class="tool-btn joined-tool-last" title="视角预设">
                    <el-icon :size="14"><View /></el-icon>
                    <el-icon class="dropdown-caret"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="top">俯视图</el-dropdown-item>
                      <el-dropdown-item command="side">侧视图</el-dropdown-item>
                      <el-dropdown-item command="iso">等距图</el-dropdown-item>
                      <el-dropdown-item command="configured" divided>重置为配置视角</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
              <span class="tool-separator"></span>
              <div class="tool-group">
                <el-button-group>
                  <el-button size="small" class="tool-btn" title="截图并下载" @click="captureSceneScreenshot">
                    <el-icon :size="14"><Camera /></el-icon>
                  </el-button>
                  <el-button
                    size="small"
                    class="tool-btn"
                    :class="{ 'recording-active': isSceneRecording }"
                    :type="isSceneRecording ? 'danger' : 'default'"
                    :title="isSceneRecording ? '结束录像并下载' : '开始录像'"
                    @click="toggleSceneRecording"
                  >
                    <el-icon :size="14">
                      <VideoPause v-if="isSceneRecording" />
                      <VideoCamera v-else />
                    </el-icon>
                  </el-button>
                </el-button-group>
              </div>
              <span class="tool-separator"></span>
              <div class="tool-group">
                <el-popover
                  v-model:visible="showRtspConnection"
                  placement="bottom-end"
                  :width="340"
                  :hide-after="0"
                  trigger="click"
                  popper-class="rtsp-connection-popper"
                >
                  <template #reference>
                    <el-button
                      size="small"
                      :type="showRtspVideo ? 'primary' : 'default'"
                      :loading="rtspConnecting"
                      class="tool-btn"
                      title="RTSP 视频连接"
                    >
                      <el-icon :size="14"><Monitor /></el-icon>
                      <el-icon class="dropdown-caret" :class="{ open: showRtspConnection }"><ArrowDown /></el-icon>
                    </el-button>
                  </template>

                  <div class="rtsp-connection-panel">
                    <div class="rtsp-connection-header">
                      <div>
                        <strong>RTSP 视频连接</strong>
                        <small>{{ showRtspVideo ? '视频流已连接' : '输入网络流地址后连接' }}</small>
                      </div>
                      <span class="rtsp-status-dot" :class="{ connected: showRtspVideo, connecting: rtspConnecting }"></span>
                    </div>

                    <label for="rtsp-toolbar-source">网络流地址</label>
                    <el-input
                      id="rtsp-toolbar-source"
                      v-model="rtspInputUrl"
                      size="small"
                      placeholder="rtsp://127.0.0.1:8554/1"
                      clearable
                      @keyup.enter="connectRtspVideo()"
                    />
                    <small class="rtsp-config-note">连接成功后，地址和视频窗口布局会随 .rvizweb 配置保存。</small>

                    <div class="rtsp-connection-actions">
                      <el-button
                        size="small"
                        type="primary"
                        :loading="rtspConnecting"
                        @click="connectRtspVideo()"
                      >
                        {{ showRtspVideo ? '切换视频流' : '连接' }}
                      </el-button>
                      <el-button
                        v-if="showRtspVideo"
                        size="small"
                        type="danger"
                        plain
                        @click="disconnectRtspVideo()"
                      >
                        关闭视频
                      </el-button>
                    </div>
                  </div>
                </el-popover>
                <el-button size="small" :type="showChartDock ? 'primary' : 'default'" @click="showChartDock = !showChartDock" class="tool-btn" title="数据图表">
                  <el-icon :size="14"><DataAnalysis /></el-icon>
                </el-button>
              </div>
            </div>
          </div>
          <div class="scene-content">
            <Scene3D
              ref="scene3dRef"
              @camera-moved="onCameraMoved"
              @display-status="onDisplayStatus"
              @tool-change="onSceneToolChange"
              @recording-change="isSceneRecording = $event"
              @frame-list-change="onFrameListChange"
            />
            <RtspVideoOverlay
              v-if="showRtspVideo && rtspStreamUrl"
              :key="rtspSessionId"
              ref="rtspVideoRef"
              :stream-url="rtspStreamUrl"
              :layout-config="settingsSnapshot.video.layout"
              @layout-change="onRtspLayoutChange"
              @edit="openRtspConnection"
              @reconnect="connectRtspVideo(rtspRuntimeSourceUrl)"
              @stream-error="handleRtspStreamError"
              @close="disconnectRtspVideo()"
            />
          </div>
        </div>

        <template v-if="showChartDock">
          <div
            class="chart-dock-resize-handle"
            @mousedown="startChartDockResize"
            @touchstart="startChartDockResize"
          >
            <span></span>
          </div>
          <WorkbenchPanel
            id="chart"
            title="数据图表"
            panel-class="chart-dock-panel"
            :style="getChartDockStyle()"
          >
            <ChartPanel :compact="true" />
          </WorkbenchPanel>
        </template>
      </section>

      <div
        class="resize-handle"
        @mousedown="startSplitterResize"
        @touchstart="startSplitterResize"
      >
        <div class="resize-line"></div>
      </div>

      <aside class="side-section">
        <div class="side-panels-container">
          <WorkbenchPanel
            id="gps"
            title="位姿信息"
            panel-class="gps-mini-panel"
            :style="getSidePanelStyle('gps')"
          >
            <GpsPanel
              :current-odom-topic="settingsSnapshot.position.odomTopic"
            />
          </WorkbenchPanel>
          <div
            class="side-panel-resize-handle"
            @mousedown="startSidePanelResize($event, 'gps')"
            @touchstart="startSidePanelResize($event, 'gps')"
          >
            <span></span>
          </div>

          <WorkbenchPanel
            id="goal"
            title="期望目标"
            panel-class="goal-mini-panel"
            :style="getSidePanelStyle('goal')"
          >
            <ExpectedGoalPanel
              :goal="settingsSnapshot.goal"
              :fixed-frame="settingsSnapshot.fixedFrame"
              @goal-update="onGoalUpdate"
              @goal-preview="onGoalPreview"
              @goal-publish="onGoalPublish"
            />
          </WorkbenchPanel>
          <div
            class="side-panel-resize-handle"
            @mousedown="startSidePanelResize($event, 'goal')"
            @touchstart="startSidePanelResize($event, 'goal')"
          >
            <span></span>
          </div>

          <WorkbenchPanel
            id="topics"
            title="Displays"
            panel-class="topic-config-mini-panel"
            :style="getSidePanelStyle('topics')"
          >
            <TopicConfigPanel
              ref="topicConfigRef"
              :displays="displaySnapshot"
              :frame-ids="availableFrameIds"
              :position-settings="settingsSnapshot.position"
              @display-topic-change="onDisplayTopicChange"
              @fixed-frame-change="onFixedFrameChange"
              @follow-frame-change="onFollowFrameChange"
              @odom-topic-change="onOdomTopicChange"
              @position-settings-change="onPositionSettingsChange"
            />
          </WorkbenchPanel>
          <div
            class="side-panel-resize-handle"
            @mousedown="startSidePanelResize($event, 'topics')"
            @touchstart="startSidePanelResize($event, 'topics')"
          >
            <span></span>
          </div>

          <WorkbenchPanel
            id="settings"
            title="设置"
            panel-class="settings-mini-panel"
            :style="getSidePanelStyle('settings')"
            collapsible
            :collapsed="settingsCollapsed"
            @update:collapsed="setPanelCollapsed('settings', $event)"
          >
            <AsyncSettingsPanel
              :settings-snapshot="settingsSnapshot"
              :display-snapshot="displaySnapshot"
              @laser-type-change="onLaserTypeChange"
              @laser2d-change="onLaser2DChange"
              @pointcloud-change="onPointCloudChange"
              @map-topic-change="onMapTopicChange"
              @odom-topic-change="onOdomTopicChange"
              @settings-update="onSettingsUpdate"
              @capture-scene-state="captureSceneState"
              @config-saved="onConfigSaved"
              @display-config-apply="onDisplayConfigApply"
              @fixed-frame-change="onConfigFixedFrameChange"
              @follow-frame-change="onConfigFollowFrameChange"
            />
          </WorkbenchPanel>
        </div>
      </aside>
    </div>
  </div>
</template>

<script>
import { ref, nextTick, defineAsyncComponent, onBeforeUnmount } from 'vue'
import {
  ArrowDown, Refresh, View, VideoCamera, VideoPause, Camera, Flag, DataAnalysis, Grid, Connection, Monitor
} from '@element-plus/icons-vue'

// 引入面板组件
import Scene3D from '../RViz/Scene3D.vue'
import RtspVideoOverlay from '../RViz/RtspVideoOverlay.vue'
import GpsPanel from '../panels/GpsPanel.vue'
import TopicConfigPanel from '../RViz/TopicConfigPanel.vue'
import WorkbenchPanel from './WorkbenchPanel.vue'
import ChartPanel from '../panels/ChartPanel.vue'
const AsyncSettingsPanel = defineAsyncComponent(() => import('../panels/SettingsPanel.vue'))
import ExpectedGoalPanel from '../panels/ExpectedGoalPanel.vue'
import { getThemeColor } from '../../utils/theme'
import { videoApi } from '../../services/api'
import { sanitizeRtspUrlForStorage } from '../../utils/rtspUrl'
import { systemMessage } from '../../composables/useSystemMessage'
import { cloneCameraState } from '../../utils/cameraState'

const DEFAULT_SIDE_PANEL_HEIGHTS = {
  gps: 220,
  goal: 220,
  topics: 560,
  settings: 360,
  chart: 300
}

const SIDE_PANEL_MIN_HEIGHTS = {
  gps: 160,
  goal: 180,
  topics: 320,
  settings: 260,
  chart: 220
}

export default {
  name: 'MainLayout',
  components: {
    ArrowDown,
    Refresh,
    View,
    VideoCamera,
    VideoPause,
    Camera,
    Flag,
    DataAnalysis,
    Grid,
    Connection,
    Monitor,
    Scene3D,
    RtspVideoOverlay,
    GpsPanel,
    TopicConfigPanel,
    WorkbenchPanel,
    ChartPanel,
    AsyncSettingsPanel,
    ExpectedGoalPanel
  },
  setup() {
    const scene3dRef = ref(null)
    const rtspVideoRef = ref(null)
    const topicConfigRef = ref(null)
    const activeSceneTool = ref('move')
    const showChartDock = ref(false)
    const showRtspVideo = ref(false)
    const showRtspConnection = ref(false)
    const rtspConnecting = ref(false)
    const rtspInputUrl = ref('')
    const rtspRuntimeSourceUrl = ref('')
    const rtspSessionId = ref('')
    const rtspStreamUrl = ref('')
    const isSceneRecording = ref(false)
    const settingsCollapsed = ref(true)
    let rtspConnectAttempt = 0
    let configuredCameraState = null
    let configuredViewPreset = 'iso'

    // 传统布局控制状态
    const sceneWidth = ref(68)
    const sceneShowGrid = ref(true)
    const sceneShowAxes = ref(true)
    const availableFrameIds = ref([])
    const isResizing = ref(false)
    const startX = ref(0)
    const startWidth = ref(0)
    const sidePanelHeights = ref({ ...DEFAULT_SIDE_PANEL_HEIGHTS })
    const sidePanelResizeState = ref({
      panelId: '',
      startY: 0,
      startHeight: 0
    })

    const settingsSnapshot = ref({
      fixedFrame: 'map',
      followFrame: '',
      scene: {
        showGrid: true,
        showAxes: true,
        viewPreset: 'iso',
        camera: null
      },
      layout: {
        sceneWidth: 68,
        panelHeights: { ...DEFAULT_SIDE_PANEL_HEIGHTS },
        collapsedPanels: {
          settings: true
        }
      },
      appearance: {
        theme: 'dark'
      },
      video: {
        sourceUrl: '',
        visible: false,
        layout: {
          x: null,
          y: null,
          width: 360,
          height: 240
        }
      },
      goal: {
        topic: '',
        x: 0,
        y: 0,
        z: 0
      },
      position: {
        odomTopic: '',
        showRobotModel: false,
        showTrajectory: true,
        trajectoryLength: 100
      },
      laser: {
        laserType: '3d',
        laserScanTopic: '',
        pointCloudTopic: '',
        showLaserPoints: true,
        showLaserLines: true,
        showIntensity: false,
        laserPointSize: 0.15,
        pointSize: 0.03,
        pointOpacity: 0.8
      },
      map: {
        mapTopic: '',
        showMap: true,
        showMapGrid: false,
        showMapOrigin: true,
        mapOpacity: 0.8
      }
    })
    const displaySnapshot = ref([])

    const normalizeTheme = (theme) => theme === 'light' ? 'light' : 'dark'

    const applyTheme = (theme) => {
      const nextTheme = normalizeTheme(theme)
      settingsSnapshot.value.appearance.theme = nextTheme
      document.documentElement.dataset.theme = nextTheme
      nextTick(() => {
        scene3dRef.value?.updateSettings?.({
          type: 'scene',
          backgroundColor: getThemeColor('--scene-background')
        })
      })
    }

    const setPanelCollapsed = (panelId, collapsed) => {
      const nextCollapsed = collapsed === true
      if (panelId === 'settings') settingsCollapsed.value = nextCollapsed
      settingsSnapshot.value.layout.collapsedPanels = {
        ...settingsSnapshot.value.layout.collapsedPanels,
        [panelId]: nextCollapsed
      }
    }

    const normalizeSidePanelHeights = (panelHeights = {}) => {
      return Object.keys(DEFAULT_SIDE_PANEL_HEIGHTS).reduce((heights, panelId) => {
        const value = Number(panelHeights[panelId])
        const fallback = DEFAULT_SIDE_PANEL_HEIGHTS[panelId]
        const minHeight = SIDE_PANEL_MIN_HEIGHTS[panelId] || 120
        heights[panelId] = Math.max(minHeight, Number.isFinite(value) ? value : fallback)
        return heights
      }, {})
    }

    const syncSidePanelHeightsToSettings = () => {
      settingsSnapshot.value.layout.panelHeights = normalizeSidePanelHeights(sidePanelHeights.value)
    }

    const getSidePanelStyle = (panelId) => ({
      height: `${sidePanelHeights.value[panelId] || DEFAULT_SIDE_PANEL_HEIGHTS[panelId]}px`
    })

    const getChartDockStyle = () => ({
      height: `${Math.max(220, Math.min(480, sidePanelHeights.value.chart || DEFAULT_SIDE_PANEL_HEIGHTS.chart))}px`
    })

    const startChartDockResize = (event) => {
      event.preventDefault()
      const startY = event.type === 'mousedown' ? event.clientY : event.touches[0].clientY
      const startHeight = sidePanelHeights.value.chart || DEFAULT_SIDE_PANEL_HEIGHTS.chart

      const handleResize = (moveEvent) => {
        moveEvent.preventDefault()
        const clientY = moveEvent.type === 'mousemove' ? moveEvent.clientY : moveEvent.touches[0].clientY
        const nextHeight = Math.max(220, Math.min(480, startHeight - (clientY - startY)))
        sidePanelHeights.value = { ...sidePanelHeights.value, chart: Math.round(nextHeight) }
        syncSidePanelHeightsToSettings()
      }

      const stopResize = () => {
        document.removeEventListener('mousemove', handleResize)
        document.removeEventListener('mouseup', stopResize)
        document.removeEventListener('touchmove', handleResize)
        document.removeEventListener('touchend', stopResize)
        document.body.style.userSelect = ''
        document.body.style.cursor = ''
      }

      document.addEventListener('mousemove', handleResize)
      document.addEventListener('mouseup', stopResize)
      document.addEventListener('touchmove', handleResize, { passive: false })
      document.addEventListener('touchend', stopResize)
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'row-resize'
    }

    const startSidePanelResize = (event, panelId) => {
      event.preventDefault()
      const clientY = event.type === 'mousedown' ? event.clientY : event.touches[0].clientY
      sidePanelResizeState.value = {
        panelId,
        startY: clientY,
        startHeight: sidePanelHeights.value[panelId] || DEFAULT_SIDE_PANEL_HEIGHTS[panelId]
      }

      document.addEventListener('mousemove', handleSidePanelResize)
      document.addEventListener('mouseup', stopSidePanelResize)
      document.addEventListener('touchmove', handleSidePanelResize, { passive: false })
      document.addEventListener('touchend', stopSidePanelResize)

      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'row-resize'
    }

    const handleSidePanelResize = (event) => {
      const { panelId, startY, startHeight } = sidePanelResizeState.value
      if (!panelId) return

      event.preventDefault()
      const clientY = event.type === 'mousemove' ? event.clientY : event.touches[0].clientY
      const minHeight = SIDE_PANEL_MIN_HEIGHTS[panelId] || 120
      const nextHeight = Math.max(minHeight, startHeight + clientY - startY)

      sidePanelHeights.value = {
        ...sidePanelHeights.value,
        [panelId]: Math.round(nextHeight)
      }
      syncSidePanelHeightsToSettings()
    }

    const stopSidePanelResize = () => {
      sidePanelResizeState.value = {
        panelId: '',
        startY: 0,
        startHeight: 0
      }

      document.removeEventListener('mousemove', handleSidePanelResize)
      document.removeEventListener('mouseup', stopSidePanelResize)
      document.removeEventListener('touchmove', handleSidePanelResize)
      document.removeEventListener('touchend', stopSidePanelResize)

      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    // 传统布局分割器拖拽功能
    const startSplitterResize = (event) => {
      isResizing.value = true
      startX.value = event.type === 'mousedown' ? event.clientX : event.touches[0].clientX
      startWidth.value = sceneWidth.value
      
      document.addEventListener('mousemove', handleResize)
      document.addEventListener('mouseup', stopResize)
      document.addEventListener('touchmove', handleResize, { passive: false })
      document.addEventListener('touchend', stopResize)
      
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'col-resize'
    }
    
    const handleResize = (event) => {
      if (!isResizing.value) return
      
      event.preventDefault()
      const currentX = event.type === 'mousemove' ? event.clientX : event.touches[0].clientX
      const deltaX = currentX - startX.value
      const containerWidth = window.innerWidth
      const deltaPercent = (deltaX / containerWidth) * 100
      
      const newWidth = Math.max(42, Math.min(78, startWidth.value + deltaPercent))
      sceneWidth.value = newWidth
      settingsSnapshot.value.layout.sceneWidth = Number(newWidth.toFixed(2))
    }
    
    const stopResize = () => {
      isResizing.value = false
      
      document.removeEventListener('mousemove', handleResize)
      document.removeEventListener('mouseup', stopResize)
      document.removeEventListener('touchmove', handleResize)
      document.removeEventListener('touchend', stopResize)
      
      document.body.style.userSelect = ''
      document.body.style.cursor = ''

      nextTick(() => {
        scene3dRef.value?.handleResize?.()
      })
    }
    
    // 3D场景控制方法
    
    const rememberConfiguredView = (sceneConfig = {}) => {
      configuredCameraState = cloneCameraState(sceneConfig.camera)
      configuredViewPreset = ['top', 'side', 'iso'].includes(sceneConfig.viewPreset)
        ? sceneConfig.viewPreset
        : 'iso'
    }

    const resetViewFromConfig = () => {
      const cameraState = cloneCameraState(configuredCameraState)
      if (cameraState && scene3dRef.value?.applyCameraState) {
        scene3dRef.value.applyCameraState(cameraState)
        settingsSnapshot.value.scene.camera = cloneCameraState(cameraState)
        settingsSnapshot.value.scene.viewPreset = configuredViewPreset
        systemMessage.info('已恢复配置文件中的相机视角')
        return
      }

      settingsSnapshot.value.scene.camera = null
      settingsSnapshot.value.scene.viewPreset = configuredViewPreset
      scene3dRef.value?.setViewPreset?.(configuredViewPreset)
      systemMessage.info(`配置未保存相机位置，已恢复${configuredViewPreset}预设`)
    }

    const refreshPointClouds = () => {
      scene3dRef.value?.refreshPointClouds?.()
    }

    const captureSceneScreenshot = () => {
      scene3dRef.value?.captureScreenshot?.()
    }

    const toggleSceneRecording = () => {
      if (isSceneRecording.value) {
        scene3dRef.value?.stopRecording?.()
      } else {
        scene3dRef.value?.startRecording?.()
      }
    }

    const releaseRtspSession = (sessionId) => {
      if (sessionId) {
        videoApi.deleteSession(sessionId).catch(() => {})
      }
    }

    const disconnectRtspVideo = (options = {}) => {
      rtspConnectAttempt += 1
      rtspConnecting.value = false
      const previousSessionId = rtspSessionId.value
      rtspSessionId.value = ''
      rtspStreamUrl.value = ''
      showRtspVideo.value = false
      if (options.updateConfig !== false) {
        settingsSnapshot.value.video.visible = false
      }
      if (options.closeConnectionPanel !== false) {
        showRtspConnection.value = false
      }
      releaseRtspSession(previousSessionId)
      if (options.notify === true) {
        systemMessage.info('RTSP 视频已关闭')
      }
    }

    const connectRtspVideo = async (
      sourceUrl = rtspInputUrl.value,
      options = {}
    ) => {
      const normalizedSource = String(sourceUrl || '').trim()
      rtspInputUrl.value = normalizedSource
      if (!/^rtsps?:\/\/[^\s]+$/i.test(normalizedSource)) {
        systemMessage.warning('请输入有效的 rtsp:// 或 rtsps:// 地址')
        return false
      }

      const attempt = ++rtspConnectAttempt
      rtspConnecting.value = true
      try {
        const session = await videoApi.createSession(normalizedSource)
        if (attempt !== rtspConnectAttempt) {
          releaseRtspSession(session.session_id)
          return false
        }

        const previousSessionId = rtspSessionId.value
        rtspSessionId.value = session.session_id
        rtspStreamUrl.value = videoApi.getStreamUrl(session.session_id)
        showRtspVideo.value = true
        showRtspConnection.value = false
        rtspRuntimeSourceUrl.value = normalizedSource
        const persistedSource = sanitizeRtspUrlForStorage(normalizedSource)
        settingsSnapshot.value.video.sourceUrl = persistedSource.sourceUrl
        settingsSnapshot.value.video.visible = !persistedSource.containsSecrets
        if (persistedSource.containsSecrets && options.notifySuccess !== false) {
          systemMessage.info('RTSP 凭据仅保留在当前页面，本次连接不会写入配置文件')
        }
        releaseRtspSession(previousSessionId)

        if (options.notifySuccess !== false) {
          systemMessage.success('RTSP 视频流连接成功')
        }
        return true
      } catch (error) {
        if (attempt !== rtspConnectAttempt) return false
        if (!showRtspVideo.value) {
          settingsSnapshot.value.video.visible = false
        }
        systemMessage.fromError(error, 'RTSP 视频连接失败或没有可用画面')
        return false
      } finally {
        if (attempt === rtspConnectAttempt) {
          rtspConnecting.value = false
        }
      }
    }

    const openRtspConnection = () => {
      rtspInputUrl.value = rtspRuntimeSourceUrl.value ||
        settingsSnapshot.value.video.sourceUrl ||
        ''
      showRtspConnection.value = true
    }

    const handleRtspStreamError = () => {
      disconnectRtspVideo({ closeConnectionPanel: false })
      systemMessage.error('RTSP 视频流已中断或没有输出画面')
    }

    const onRtspLayoutChange = (layout) => {
      settingsSnapshot.value.video.layout = {
        ...settingsSnapshot.value.video.layout,
        ...layout
      }
    }

    const activateSceneTool = (tool) => {
      scene3dRef.value?.setGoalTopic?.(settingsSnapshot.value.goal.topic)
      scene3dRef.value?.setNavigationTool?.(tool)
    }

    const onSceneToolChange = (tool) => {
      activeSceneTool.value = tool || 'move'
    }

    const onCameraMoved = (cameraState) => {
      if (cameraState) {
        settingsSnapshot.value.scene.camera = cameraState
      }
    }

    const toggleGrid = () => {
      sceneShowGrid.value = !sceneShowGrid.value
      settingsSnapshot.value.scene.showGrid = sceneShowGrid.value
      if (scene3dRef.value?.setGridVisible) {
        scene3dRef.value.setGridVisible(sceneShowGrid.value)
      }
    }
    
    const toggleAxes = () => {
      sceneShowAxes.value = !sceneShowAxes.value
      settingsSnapshot.value.scene.showAxes = sceneShowAxes.value
      if (scene3dRef.value?.setAxesVisible) {
        scene3dRef.value.setAxesVisible(sceneShowAxes.value)
      }
    }

    const setSceneViewPreset = (preset) => {
      if (preset === 'configured') {
        resetViewFromConfig()
        return
      }
      settingsSnapshot.value.scene.viewPreset = preset
      settingsSnapshot.value.scene.camera = null
      if (scene3dRef.value?.setViewPreset) {
        scene3dRef.value.setViewPreset(preset)
      }
    }
    
    const setExpectedTargetTool = (tool) => {
      if (tool === '3d_goal') {
        systemMessage.info('3D期望功能稍后开放')
        return
      }

      if (scene3dRef.value?.setNavigationTool) {
        scene3dRef.value.setNavigationTool(tool)
        systemMessage.info('左键按下选择目标点，移动鼠标设置方向，松开发送；按 X 取消')
      } else {
        systemMessage.warning('3D场景未就绪')
      }
    }
    
    const onTopicSubscribe = (topicName, messageType) => {
      console.log(`订阅主题: ${topicName}, 类型: ${messageType}`)
      
      if (scene3dRef.value && scene3dRef.value.subscribeToRosTopic) {
        // 直接让3D场景组件处理ROS主题订阅
        scene3dRef.value.subscribeToRosTopic(topicName, messageType)
        systemMessage.success(`已订阅可视化主题: ${topicName}`)
      } else {
        console.warn('3D场景未就绪或不支持该消息类型')
      }
    }
    
    const onTopicUnsubscribe = (topicName) => {
      console.log(`取消订阅主题: ${topicName}`)
      if (scene3dRef.value && scene3dRef.value.unsubscribeFromRosTopic) {
        scene3dRef.value.unsubscribeFromRosTopic(topicName)
        systemMessage.info(`已取消订阅主题: ${topicName}`)
      }
    }
    
    // 旧配置中的激光和地图字段仍通过统一设置通道恢复
    const onLaserTypeChange = (laserType) => {
      console.log(`激光类型切换: ${laserType}`)
      settingsSnapshot.value.laser.laserType = laserType
    }

    const isTopicStillConfigured = (topicName) => {
      if (!topicName) return false
      return topicName === settingsSnapshot.value.position.odomTopic ||
        topicName === settingsSnapshot.value.laser.laserScanTopic ||
        topicName === settingsSnapshot.value.laser.pointCloudTopic ||
        topicName === settingsSnapshot.value.map.mapTopic ||
        displaySnapshot.value.some(display =>
          display.visible !== false && display.name === topicName
        )
    }

    const replaceConfiguredTopic = (section, key, topicName, messageType) => {
      const nextTopic = topicName || ''
      const previousTopic = settingsSnapshot.value[section][key]
      settingsSnapshot.value[section][key] = nextTopic

      if (previousTopic && previousTopic !== nextTopic && !isTopicStillConfigured(previousTopic)) {
        scene3dRef.value?.unsubscribeFromRosTopic?.(previousTopic)
      }
      if (nextTopic) {
        onTopicSubscribe(nextTopic, messageType)
      }
    }

    const onLaser2DChange = (topicName) => {
      console.log(`2D激光主题切换: ${topicName}`)
      replaceConfiguredTopic('laser', 'laserScanTopic', topicName, 'sensor_msgs/msg/LaserScan')
    }

    const onPointCloudChange = (topicName) => {
      console.log(`点云主题切换: ${topicName}`)
      replaceConfiguredTopic('laser', 'pointCloudTopic', topicName, 'sensor_msgs/msg/PointCloud2')
    }

    const onMapTopicChange = (topicName) => {
      console.log(`地图主题切换: ${topicName}`)
      replaceConfiguredTopic('map', 'mapTopic', topicName, 'nav_msgs/msg/OccupancyGrid')
    }

    const onOdomTopicChange = (topicName) => {
      const nextTopic = topicName || ''
      const previousTopic = settingsSnapshot.value.position.odomTopic
      console.log(`里程计主题切换: ${nextTopic}`)

      settingsSnapshot.value.position.odomTopic = nextTopic
      if (previousTopic && previousTopic !== nextTopic && !isTopicStillConfigured(previousTopic)) {
        scene3dRef.value?.unsubscribeFromRosTopic?.(previousTopic)
      }
      if (!nextTopic) {
        settingsSnapshot.value.position.showRobotModel = false
      }

      scene3dRef.value?.setPositionOdomTopic?.(nextTopic)
      scene3dRef.value?.setRobotModelVisible?.(
        Boolean(nextTopic && settingsSnapshot.value.position.showRobotModel)
      )

      if (nextTopic) {
        onTopicSubscribe(nextTopic, 'nav_msgs/msg/Odometry')
      }
    }

    const onPositionSettingsChange = (settings) => {
      onSettingsUpdate({
        type: 'position',
        ...settings
      })
    }

    const onSettingsUpdate = (settings) => {
      console.log('设置更新:', settings)
      let sceneSettings = settings
      if (settings.type === 'laser') {
        settingsSnapshot.value.laser.showLaserPoints = settings.showLaserPoints
        settingsSnapshot.value.laser.showLaserLines = settings.showLaserLines
        settingsSnapshot.value.laser.showIntensity = settings.showIntensity
        settingsSnapshot.value.laser.laserPointSize = settings.pointSize
      } else if (settings.type === 'pointcloud') {
        settingsSnapshot.value.laser.pointSize = settings.pointSize
        settingsSnapshot.value.laser.pointOpacity = settings.opacity
        settingsSnapshot.value.laser.showIntensity = settings.showIntensity
      } else if (settings.type === 'map') {
        if (settings.showMap !== undefined) settingsSnapshot.value.map.showMap = settings.showMap
        if (settings.opacity !== undefined) settingsSnapshot.value.map.mapOpacity = settings.opacity
        if (settings.showGrid !== undefined) settingsSnapshot.value.map.showMapGrid = settings.showGrid
        if (settings.showOrigin !== undefined) settingsSnapshot.value.map.showMapOrigin = settings.showOrigin
      } else if (settings.type === 'position') {
        if (settings.showTrajectory !== undefined) {
          settingsSnapshot.value.position.showTrajectory = settings.showTrajectory
        }
        if (settings.trajectoryLength !== undefined) {
          settingsSnapshot.value.position.trajectoryLength = settings.trajectoryLength
        }
        if (settings.showRobotModel !== undefined) {
          const showRobotModel = settings.showRobotModel === true &&
            Boolean(settingsSnapshot.value.position.odomTopic)
          settingsSnapshot.value.position.showRobotModel = showRobotModel
          sceneSettings = { ...settings, showRobotModel }
        }
      } else if (settings.type === 'trajectory') {
        settingsSnapshot.value.position.trajectoryLength = settings.trajectoryLength
      } else if (settings.type === 'scene') {
        if (settings.source === 'config') {
          rememberConfiguredView(settings)
        }
        if (settings.showGrid !== undefined) {
          sceneShowGrid.value = settings.showGrid
          settingsSnapshot.value.scene.showGrid = settings.showGrid
        }
        if (settings.showAxes !== undefined) {
          sceneShowAxes.value = settings.showAxes
          settingsSnapshot.value.scene.showAxes = settings.showAxes
        }
        if (settings.viewPreset) {
          settingsSnapshot.value.scene.viewPreset = settings.viewPreset
        }
        if (Object.prototype.hasOwnProperty.call(settings, 'camera')) {
          settingsSnapshot.value.scene.camera = settings.camera
        }
      } else if (settings.type === 'appearance') {
        applyTheme(settings.theme)
      } else if (settings.type === 'video') {
        const video = settings.video || settings
        const sourceUrl = typeof video.sourceUrl === 'string' ? video.sourceUrl.trim() : ''
        const shouldConnect = video.visible === true && Boolean(sourceUrl)
        settingsSnapshot.value.video = {
          sourceUrl,
          visible: shouldConnect,
          layout: {
            x: Number.isFinite(video.layout?.x) ? video.layout.x : null,
            y: Number.isFinite(video.layout?.y) ? video.layout.y : null,
            width: Number.isFinite(video.layout?.width) ? video.layout.width : 360,
            height: Number.isFinite(video.layout?.height) ? video.layout.height : 240
          }
        }
        rtspInputUrl.value = sourceUrl
        rtspRuntimeSourceUrl.value = sourceUrl
        if (shouldConnect) {
          connectRtspVideo(sourceUrl, { notifySuccess: false })
        } else {
          disconnectRtspVideo({
            updateConfig: false,
            closeConnectionPanel: false
          })
        }
      } else if (settings.type === 'layout') {
        if (typeof settings.sceneWidth === 'number') {
          const nextWidth = Math.max(42, Math.min(78, settings.sceneWidth))
          sceneWidth.value = nextWidth
          settingsSnapshot.value.layout.sceneWidth = Number(nextWidth.toFixed(2))
          nextTick(() => {
            scene3dRef.value?.handleResize?.()
          })
        }
        if (settings.panelHeights) {
          sidePanelHeights.value = normalizeSidePanelHeights(settings.panelHeights)
          syncSidePanelHeightsToSettings()
        }
        if (settings.collapsedPanels) {
          if (typeof settings.collapsedPanels.settings === 'boolean') {
            setPanelCollapsed('settings', settings.collapsedPanels.settings)
          }
        }
      } else if (settings.type === 'goal') {
        onGoalUpdate(settings.goal || settings)
      }
      if (scene3dRef.value && scene3dRef.value.updateSettings) {
        scene3dRef.value.updateSettings(sceneSettings)
      }
    }

    const onConfigSaved = (config) => {
      rememberConfiguredView(config?.scene)
    }

    const normalizeGoal = (goal) => ({
      topic: typeof goal?.topic === 'string' ? goal.topic.trim() : '',
      x: Number(goal?.x) || 0,
      y: Number(goal?.y) || 0,
      z: Number(goal?.z) || 0
    })

    const onGoalUpdate = (goal) => {
      const nextGoal = normalizeGoal(goal)
      settingsSnapshot.value.goal = nextGoal
      scene3dRef.value?.setGoalTopic?.(nextGoal.topic)
    }

    const onGoalPreview = (goal) => {
      const nextGoal = normalizeGoal(goal)
      settingsSnapshot.value.goal = nextGoal
      scene3dRef.value?.previewGoalPoseFromInput?.(nextGoal)
    }

    const onGoalPublish = async (goal) => {
      const nextGoal = normalizeGoal(goal)
      settingsSnapshot.value.goal = nextGoal
      const publishGoal = scene3dRef.value?.publishGoalPoseFromInput
      if (!publishGoal) {
        systemMessage.warning('3D场景未就绪')
        return
      }
      await publishGoal(nextGoal, nextGoal.topic)
    }

    const setDisplayTopicVisible = (topicName, visible) => {
      if (scene3dRef.value?.setVisualizationVisible) {
        scene3dRef.value.setVisualizationVisible(topicName, visible)
      }
    }

    const isPositionOdomTopic = (topicName, messageType = '') => {
      return !!topicName &&
        topicName === settingsSnapshot.value.position.odomTopic &&
        (messageType.includes('Odometry') || !messageType || messageType === 'unknown')
    }

    const ensurePositionOdomSubscription = () => {
      const odomTopic = settingsSnapshot.value.position.odomTopic
      if (odomTopic && scene3dRef.value?.subscribeToRosTopic) {
        scene3dRef.value.subscribeToRosTopic(odomTopic, 'nav_msgs/msg/Odometry')
      }
    }

    const removeDisplayVisualization = (topicName, messageType) => {
      if (isPositionOdomTopic(topicName, messageType)) return
      scene3dRef.value?.removeVisualization?.(topicName)
    }

    const unsubscribeDisplayTopic = (topicName, messageType) => {
      if (isPositionOdomTopic(topicName, messageType)) return
      if (scene3dRef.value?.unsubscribeFromRosTopic) {
        scene3dRef.value.unsubscribeFromRosTopic(topicName)
      } else {
        scene3dRef.value?.removeVisualization?.(topicName)
      }
    }

    const upsertDisplaySnapshot = (display) => {
      const index = displaySnapshot.value.findIndex(item => item.name === display.name)
      const nextDisplay = {
        name: display.name,
        messageType: display.messageType,
        visible: display.visible !== false,
        config: display.config || {}
      }
      if (index >= 0) {
        displaySnapshot.value.splice(index, 1, nextDisplay)
      } else {
        displaySnapshot.value.push(nextDisplay)
      }
    }

    const onDisplayTopicChange = ({ action, display, oldName }) => {
      if (!display?.name) return

      const scene = scene3dRef.value
      if (!scene) {
        systemMessage.warning('3D场景未就绪')
        return
      }

      const topicName = display.name
      const messageType = display.messageType || 'unknown'
      const previousTopicName = oldName || topicName

      switch (action) {
        case 'add':
          upsertDisplaySnapshot(display)
          scene.configureDisplay?.(topicName, display.config || {})
          scene.removeVisualization?.(topicName)
          if (display.visible !== false && scene.subscribeToRosTopic) {
            scene.subscribeToRosTopic(topicName, messageType)
          }
          setDisplayTopicVisible(topicName, display.visible !== false)
          break
        case 'show':
          upsertDisplaySnapshot({ ...display, visible: true })
          scene.configureDisplay?.(topicName, display.config || {})
          scene.removeVisualization?.(topicName)
          if (scene.subscribeToRosTopic) {
            scene.subscribeToRosTopic(topicName, messageType)
          }
          setDisplayTopicVisible(topicName, true)
          break
        case 'hide':
          upsertDisplaySnapshot({ ...display, visible: false })
          unsubscribeDisplayTopic(topicName, messageType)
          break
        case 'remove':
          displaySnapshot.value = displaySnapshot.value.filter(item => item.name !== topicName)
          unsubscribeDisplayTopic(topicName, messageType)
          break
        case 'update':
          if (previousTopicName !== topicName) {
            displaySnapshot.value = displaySnapshot.value.filter(item => item.name !== previousTopicName)
          }
          upsertDisplaySnapshot(display)
          scene.configureDisplay?.(topicName, display.config || {})
          // 同一话题的样式更新直接作用到当前对象，避免拖动尺寸时反复退订和重订。
          if (previousTopicName === topicName) {
            setDisplayTopicVisible(topicName, display.visible !== false)
            break
          }
          unsubscribeDisplayTopic(previousTopicName, messageType)
          unsubscribeDisplayTopic(topicName, messageType)
          removeDisplayVisualization(previousTopicName, messageType)
          removeDisplayVisualization(topicName, messageType)
          if (display.visible !== false && scene.subscribeToRosTopic) {
            scene.subscribeToRosTopic(topicName, messageType)
          } else {
            removeDisplayVisualization(topicName, messageType)
          }
          break
        default:
          console.warn('未知话题控制动作:', action, display)
      }
    }

    const onDisplayConfigApply = (displays) => {
      displaySnapshot.value = Array.isArray(displays)
        ? displays.map(display => ({
            name: display.name,
            messageType: display.messageType,
            visible: display.visible !== false,
            config: display.config || {}
          })).filter(display => display.name && display.messageType)
        : []
      topicConfigRef.value?.applyDisplays?.(displaySnapshot.value)
      ensurePositionOdomSubscription()
    }

    const onFixedFrameChange = (frameId) => {
      const nextFrameId = frameId || 'map'
      console.log(`Fixed Frame切换: ${nextFrameId}`)
      settingsSnapshot.value.fixedFrame = nextFrameId
      if (scene3dRef.value?.setFixedFrame) {
        scene3dRef.value.setFixedFrame(nextFrameId)
      }
    }

    const onFrameListChange = (frameIds) => {
      availableFrameIds.value = Array.isArray(frameIds) ? frameIds : []
    }

    const onFollowFrameChange = (frameId) => {
      const nextFrameId = frameId || ''
      settingsSnapshot.value.followFrame = nextFrameId
      scene3dRef.value?.setFollowFrame?.(nextFrameId)
    }

    const onDisplayStatus = ({ topic, error }) => {
      topicConfigRef.value?.setDisplayStatus?.(topic, error || '')
    }

    const onConfigFixedFrameChange = (frameId) => {
      const nextFrameId = frameId || 'map'
      topicConfigRef.value?.setFixedFrameSilently?.(nextFrameId)
      onFixedFrameChange(nextFrameId)
    }

    const onConfigFollowFrameChange = (frameId) => {
      const nextFrameId = frameId || ''
      topicConfigRef.value?.setFollowFrameSilently?.(nextFrameId)
      onFollowFrameChange(nextFrameId)
    }

    const captureSceneState = () => {
      const camera = scene3dRef.value?.getCameraState?.()
      if (camera) {
        settingsSnapshot.value.scene.camera = camera
      }
      settingsSnapshot.value.layout.sceneWidth = Number(sceneWidth.value.toFixed(2))
      syncSidePanelHeightsToSettings()
      settingsSnapshot.value.layout.collapsedPanels = {
        settings: settingsCollapsed.value
      }
      const videoLayout = rtspVideoRef.value?.getLayout?.()
      if (videoLayout) {
        onRtspLayoutChange(videoLayout)
      }
    }

    onBeforeUnmount(() => {
      rtspConnectAttempt += 1
      releaseRtspSession(rtspSessionId.value)
      rtspSessionId.value = ''
      rtspStreamUrl.value = ''
    })

    return {
      scene3dRef,
      rtspVideoRef,
      topicConfigRef,
      activeSceneTool,
      showChartDock,
      showRtspVideo,
      showRtspConnection,
      rtspConnecting,
      rtspInputUrl,
      rtspSessionId,
      rtspStreamUrl,
      isSceneRecording,
      settingsCollapsed,
      setPanelCollapsed,
      settingsSnapshot,
      availableFrameIds,
      displaySnapshot,
      sceneWidth,
      sidePanelHeights,
      startSplitterResize,
      getSidePanelStyle,
      getChartDockStyle,
      startChartDockResize,
      startSidePanelResize,
      refreshPointClouds,
      captureSceneScreenshot,
      toggleSceneRecording,
      connectRtspVideo,
      disconnectRtspVideo,
      openRtspConnection,
      handleRtspStreamError,
      onRtspLayoutChange,
      activateSceneTool,
      onSceneToolChange,
      toggleGrid,
      toggleAxes,
      setSceneViewPreset,
      setExpectedTargetTool,
      sceneShowGrid,
      sceneShowAxes,
      onTopicSubscribe,
      onTopicUnsubscribe,
      onLaserTypeChange,
      onLaser2DChange,
      onPointCloudChange,
      onMapTopicChange,
      onOdomTopicChange,
      onPositionSettingsChange,
      onSettingsUpdate,
      onConfigSaved,
      onGoalUpdate,
      onGoalPreview,
      onGoalPublish,
      onDisplayTopicChange,
      onDisplayConfigApply,
      onCameraMoved,
      onFixedFrameChange,
      onFollowFrameChange,
      onFrameListChange,
      onDisplayStatus,
      onConfigFixedFrameChange,
      onConfigFollowFrameChange,
      captureSceneState
    }
  }
}
</script>

<style scoped>
.main-layout {
  height: 100%;
  min-height: 0;
  background: var(--bg-surface);
}

.main-content {
  height: 100%;
  min-height: 0;
  display: grid;
  gap: 0;
    padding: 6px;
  min-width: 0;
  min-height: 0;
}

.scene-section {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.scene-panel {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.chart-dock-panel {
  flex: 0 0 auto;
  min-width: 0;
}

.chart-dock-resize-handle {
  flex: 0 0 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  user-select: none;
  touch-action: none;
}

.chart-dock-resize-handle span {
  width: 54px;
  height: 4px;
  border-radius: 999px;
  background: var(--handle);
  transition: width 0.16s ease, background-color 0.16s ease;
}

.chart-dock-resize-handle:hover span,
.chart-dock-resize-handle:active span {
  width: 84px;
  background: var(--handle-hover);
}

.scene-header {
  min-height: 40px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
    gap: 8px;
    padding: 0 8px 0 10px;
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.scene-controls {
  display: flex;
  align-items: center;
    gap: 6px;
  padding: 3px 0;
}

.scene-content {
  flex: 1;
  min-height: 0;
  position: relative;
}

.resize-handle {
    width: 8px;
    min-width: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: col-resize;
  user-select: none;
  touch-action: none;
}

.resize-line {
  width: 4px;
  height: 54px;
  border-radius: 999px;
  background: var(--handle);
  transition: background-color 0.16s ease, height 0.16s ease;
}

.resize-handle:hover .resize-line,
.resize-handle:active .resize-line {
  height: 84px;
  background: var(--handle-hover);
}

.side-section {
  height: 100%;
  overflow: hidden;
}

.side-panels-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.gps-mini-panel,
.topic-config-mini-panel,
.goal-mini-panel,
.settings-mini-panel,
.chart-mini-panel {
  flex: 0 0 auto;
  min-width: 0;
}

.side-panel-resize-handle {
    flex: 0 0 8px;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  user-select: none;
  touch-action: none;
}

.side-panel-resize-handle span {
  width: 56px;
  height: 4px;
  border-radius: 999px;
  background: var(--handle);
  transition: width 0.16s ease, background-color 0.16s ease;
}

.side-panel-resize-handle:hover span,
.side-panel-resize-handle:active span {
  width: 88px;
  background: var(--handle-hover);
}

.side-panels-container::-webkit-scrollbar,
:deep(.workbench-panel-content::-webkit-scrollbar) {
  width: 8px;
  height: 8px;
}

.side-panels-container::-webkit-scrollbar-track,
:deep(.workbench-panel-content::-webkit-scrollbar-track) {
  background: var(--bg-elevated);
}

.side-panels-container::-webkit-scrollbar-thumb,
:deep(.workbench-panel-content::-webkit-scrollbar-thumb) {
  background: var(--scrollbar-thumb);
  border-radius: 999px;
}

:deep(.el-button) {
  border-color: var(--border-strong);
}

/* ---- toolbar ---- */

.tool-group {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
}

.view-tool-group {
  gap: 0;
}

.view-tool-group :deep(.joined-tool-middle),
.view-tool-group :deep(.joined-tool-last) {
  margin-left: -1px;
  border-radius: 0;
}

.view-tool-group :deep(.joined-tool-first) {
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}

.view-tool-group :deep(.joined-tool-last) {
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.view-tool-group :deep(.el-button:hover),
.view-tool-group :deep(.el-button:focus-visible),
.view-tool-group :deep(.el-button:active) {
  position: relative;
  z-index: 1;
}

.tool-separator {
  flex: 0 0 auto;
  width: 1px;
  height: 20px;
  background: var(--border);
  margin: 0 4px;
  border-radius: 1px;
}

.tool-btn kbd {
  font-size: 9px;
  font-family: inherit;
  padding: 0 3px;
  margin-left: 2px;
  border-radius: 3px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-muted);
  line-height: 1.5;
  opacity: 0.7;
}

.dropdown-caret {
  margin-left: 1px !important;
  font-size: 10px;
  transition: transform 0.16s ease;
}

.dropdown-caret.open {
  transform: rotate(180deg);
}

:global(.rtsp-connection-popper.el-popover) {
  padding: 12px;
  background: var(--bg-panel);
  border-color: var(--border);
  box-shadow: 0 16px 40px var(--shadow-color-35);
}

.rtsp-connection-panel {
  display: grid;
  gap: 9px;
}

.rtsp-connection-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-muted);
}

.rtsp-connection-header > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.rtsp-connection-header strong {
  color: var(--text-primary);
  font-size: 13px;
}

.rtsp-connection-header small,
.rtsp-config-note,
.rtsp-connection-panel label {
  color: var(--text-muted);
  font-size: 10px;
}

.rtsp-status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--text-muted);
}

.rtsp-status-dot.connected {
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-soft);
}

.rtsp-status-dot.connecting {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-soft);
}

.rtsp-config-note {
  line-height: 1.45;
}

.rtsp-connection-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 2px;
}

:deep(.recording-active),
:deep(.recording-active:hover),
:deep(.recording-active:focus) {
  color: #fff !important;
  background: var(--danger) !important;
  border-color: var(--danger) !important;
  box-shadow: 0 0 0 2px var(--danger-soft);
}

@media (max-width: 1100px) {
  .main-content {
    grid-template-columns: 1fr !important;
    grid-template-rows: minmax(55vh, 1fr) auto;
    gap: 8px;
    overflow: auto;
  }

  .resize-handle {
    display: none;
  }

  .side-panels-container {
    height: auto;
  }
}
</style>
