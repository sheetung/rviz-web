<template>
  <div
    ref="containerRef"
    class="scene3d-container"
    tabindex="0"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
  >
    <!-- 加载指示器 -->
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner">
        <div class="spinner"></div>
      </div>
      <span>初始化 3D 场景...</span>
    </div>
    
    <div class="tool-hint" v-show="!loading">
      <div class="hint-content">
        <strong>{{ activeToolLabel }}</strong>
        <small>{{ toolHint }}</small>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import * as THREE from 'three'
import { useRosbridge } from '../../composables/useRosbridge'
import { useConnectionStore } from '../../composables/useConnectionStore'
import { ROS_TOPICS, getDefaultVisualizationTopics, getPositionTopics } from '../../config/rosTopics'
import { FollowFrameTracker, TfBuffer, frameIdFromMessage, messageTimestampMs } from '../../utils/tfBuffer'
import {
  markerLifetimeMilliseconds,
  markerTransformTimestamp,
  refreshMarkerGroupTransforms
} from '../../utils/markerState'
import { debugLog } from '../../utils/debug'
import { getThemeColor } from '../../utils/theme'
import { systemMessage } from '../../composables/useSystemMessage'
import {
  createHeightColoredBoxesMaterial,
  createHeightColoredPointsMaterial
} from '../../utils/pointCloudMaterial'

export default {
  name: 'Scene3D',
  emits: ['object-selected', 'camera-moved', 'display-status', 'tool-change', 'recording-change', 'frame-list-change'],
  setup(props, { emit }) {
    const rosbridge = useRosbridge()
    const connectionStore = useConnectionStore()
    const containerRef = ref(null)
    const loading = ref(true)
    const activeTool = ref('move')
    const activeToolLabel = ref('移动相机 (M)')
    const toolHint = ref('左键旋转 · 中键平移 · 滚轮缩放')
    
    // Three.js 核心对象
    let scene = null
    let camera = null
    let perspectiveCamera = null
    let orthographicCamera = null
    let renderer = null
    let controls = null
    let animationId = null
    let mediaRecorder = null
    let recordingStream = null
    let recordingChunks = []

    const createCaptureFilename = (extension) => {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').replace('Z', '')
      return `rvizweb_${stamp}.${extension}`
    }

    const downloadBlob = (blob, filename) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }

    const captureScreenshot = () => {
      if (!renderer || !scene || !camera) {
        systemMessage.warning('3D场景尚未就绪')
        return false
      }
      renderer.render(scene, camera)
      renderer.domElement.toBlob(blob => {
        if (!blob) {
          systemMessage.error('截图生成失败')
          return
        }
        downloadBlob(blob, createCaptureFilename('png'))
        systemMessage.success('截图已生成')
      }, 'image/png')
      return true
    }

    const getRecordingFormat = () => {
      const candidates = [
        { mimeType: 'video/webm;codecs=vp9', extension: 'webm' },
        { mimeType: 'video/webm;codecs=vp8', extension: 'webm' },
        { mimeType: 'video/webm', extension: 'webm' }
      ]
      return candidates.find(format => MediaRecorder.isTypeSupported(format.mimeType)) || {
        mimeType: '',
        extension: 'webm'
      }
    }

    const releaseRecordingStream = () => {
      recordingStream?.getTracks().forEach(track => track.stop())
      recordingStream = null
    }

    const startRecording = () => {
      if (mediaRecorder?.state === 'recording') return true
      const canvas = renderer?.domElement
      if (!canvas || typeof canvas.captureStream !== 'function' || typeof MediaRecorder === 'undefined') {
        systemMessage.error('当前浏览器不支持画布录像')
        return false
      }

      try {
        recordingChunks = []
        recordingStream = canvas.captureStream(30)
        const recordingFormat = getRecordingFormat()
        mediaRecorder = new MediaRecorder(
          recordingStream,
          recordingFormat.mimeType ? { mimeType: recordingFormat.mimeType } : undefined
        )
        mediaRecorder.ondataavailable = event => {
          if (event.data?.size > 0) recordingChunks.push(event.data)
        }
        mediaRecorder.onerror = () => {
          releaseRecordingStream()
          emit('recording-change', false)
          systemMessage.error('录像过程发生错误')
        }
        mediaRecorder.onstop = () => {
          const outputType = mediaRecorder?.mimeType || recordingFormat.mimeType || 'video/webm'
          if (recordingChunks.length > 0) {
            downloadBlob(new Blob(recordingChunks, { type: outputType }), createCaptureFilename(recordingFormat.extension))
            systemMessage.success('录像已生成')
          } else {
            systemMessage.warning('录像中没有可用画面')
          }
          recordingChunks = []
          releaseRecordingStream()
          mediaRecorder = null
          emit('recording-change', false)
        }
        mediaRecorder.start(250)
        emit('recording-change', true)
        systemMessage.success('开始录制点云视图')
        return true
      } catch (error) {
        releaseRecordingStream()
        mediaRecorder = null
        emit('recording-change', false)
        systemMessage.error(`无法开始录像: ${error.message}`)
        return false
      }
    }

    const stopRecording = () => {
      if (!mediaRecorder || mediaRecorder.state === 'inactive') return false
      mediaRecorder.stop()
      return true
    }
    let containerResizeObserver = null
    
    // 场景对象
    let gridHelper = null
    let axesHelper = null
    let ambientLight = null
    let directionalLight = null
    
    // 性能监控
    const performanceStats = ref({
      fps: 0,
      objects: 0,
      vertices: 0
    })
    
    // 可视化对象和ROS订阅管理
    const visualizationObjects = new Map()
    const rosSubscriptions = new Map()
    const displayConfigs = new Map()
    const markerLifetimeTimers = new Map()
    const positionCommandPaths = new Map()
    const tfBuffer = new TfBuffer()
    const followFrameTracker = new FollowFrameTracker()
    const observedFrameIds = new Set()
    const pendingPointClouds = new Map()
    const pointCloudDecodesInFlight = new Map()
    const latestDisplayMessages = new Map()
    let pointCloudFrameRequest = null
    let pointCloudWorker = null
    let pointCloudWorkerDisabled = false
    let pointCloudGeneration = 0
    let transformFrameRequest = null
    let frameListSignature = ''

    const emitFrameList = () => {
      const frameIds = [...new Set([
        ...tfBuffer.frameIds(),
        ...observedFrameIds
      ])].sort((left, right) => left.localeCompare(right))
      const signature = frameIds.join('\n')
      if (signature === frameListSignature) return
      frameListSignature = signature
      emit('frame-list-change', frameIds)
    }

    const observeMessageFrames = (message) => {
      const frames = [
        frameIdFromMessage(message),
        ...(message?.markers || []).map(marker => frameIdFromMessage(marker))
      ].filter(Boolean)
      const previousSize = observedFrameIds.size
      frames.forEach(frame => observedFrameIds.add(frame))
      if (observedFrameIds.size !== previousSize) emitFrameList()
    }

    const applyFollowFrame = () => {
      const translation = followFrameTracker.update(tfBuffer, fixedFrameId)
      if (!translation || !camera || !controls) return
      camera.position.add(translation)
      controls.target.add(translation)
      controls.update()
    }

    const setDisplayStatus = (topic, error = '') => {
      emit('display-status', { topic, error })
    }

    const pointCloudTransformMessage = (message) => ({
      header: message?.header
    })

    const applyFixedFrame = (
      topic,
      message,
      object = visualizationObjects.get(topic),
      report = true,
      transformTimestamp = messageTimestampMs(message)
    ) => {
      if (!object) return true
      if (object.userData?.fixedFrameApplied) return true
      const sourceFrame = frameIdFromMessage(message) || frameIdFromMessage(message?.markers?.[0])
      if (!sourceFrame || sourceFrame === fixedFrameId.replace(/^\/+/, '')) {
        if (object.userData?.fixedFrameBaseMatrix) {
          object.matrixAutoUpdate = false
          object.matrix.copy(object.userData.fixedFrameBaseMatrix)
          object.matrixWorldNeedsUpdate = true
        }
        object.visible = true
        if (report) setDisplayStatus(topic)
        return true
      }
      const transform = tfBuffer.lookupTransform(fixedFrameId, sourceFrame, transformTimestamp)
      if (!transform) {
        object.visible = false
        if (report) setDisplayStatus(topic, `缺少 ${sourceFrame} → ${fixedFrameId} 的 TF`)
        return false
      }
      object.updateMatrix()
      if (!object.userData.fixedFrameBaseMatrix) {
        object.userData.fixedFrameBaseMatrix = object.matrix.clone()
      }
      object.matrixAutoUpdate = false
      object.matrix.copy(object.userData.fixedFrameBaseMatrix).premultiply(transform)
      object.matrixWorldNeedsUpdate = true
      object.visible = true
      if (report) setDisplayStatus(topic)
      return true
    }

    const schedulePointCloudFlush = () => {
      if (pointCloudFrameRequest === null && pendingPointClouds.size > 0) {
        pointCloudFrameRequest = requestAnimationFrame(flushPointCloudUpdates)
      }
    }

    const disablePointCloudWorker = (error) => {
      if (pointCloudWorkerDisabled) return
      pointCloudWorkerDisabled = true
      pointCloudWorker?.terminate()
      pointCloudWorker = null
      pointCloudDecodesInFlight.forEach(({ message }, topic) => {
        if (!pendingPointClouds.has(topic)) pendingPointClouds.set(topic, message)
      })
      pointCloudDecodesInFlight.clear()
      console.warn('[Scene3D] PointCloud Worker 不可用，回退到主线程解码:', error)
      schedulePointCloudFlush()
    }

    const ensurePointCloudWorker = () => {
      if (pointCloudWorker || pointCloudWorkerDisabled) return pointCloudWorker
      if (typeof Worker === 'undefined') {
        pointCloudWorkerDisabled = true
        return null
      }
      try {
        pointCloudWorker = new Worker(
          new URL('../../workers/pointCloudWorker.js', import.meta.url),
          { type: 'module' }
        )
        pointCloudWorker.onmessage = (event) => {
          const { topic, generation, decoded } = event.data || {}
          const inFlight = pointCloudDecodesInFlight.get(topic)
          if (!inFlight || inFlight.generation !== generation) return
          pointCloudDecodesInFlight.delete(topic)

          if (rosSubscriptions.has(topic)) {
            updateDecodedPointCloud(topic, inFlight.message, decoded)
            applyFixedFrame(topic, inFlight.message)
          }
          schedulePointCloudFlush()
        }
        pointCloudWorker.onerror = (event) => {
          disablePointCloudWorker(event?.message || 'Worker error')
        }
        pointCloudWorker.onmessageerror = () => {
          disablePointCloudWorker('Worker message decode error')
        }
      } catch (error) {
        disablePointCloudWorker(error)
      }
      return pointCloudWorker
    }

    const flushPointCloudUpdates = () => {
      pointCloudFrameRequest = null
      const worker = ensurePointCloudWorker()
      pendingPointClouds.forEach((message, topic) => {
        if (pointCloudDecodesInFlight.has(topic)) return
        pendingPointClouds.delete(topic)

        if (!worker || pointCloudWorkerDisabled) {
          updatePointCloud(topic, message)
          applyFixedFrame(topic, message)
          return
        }

        const generation = ++pointCloudGeneration
        pointCloudDecodesInFlight.set(topic, { generation, message })
        try {
          const transferable = ArrayBuffer.isView(message?.data)
            ? [message.data.buffer]
            : message?.data instanceof ArrayBuffer
              ? [message.data]
              : []
          worker.postMessage({ topic, generation, message }, transferable)
        } catch (error) {
          pointCloudDecodesInFlight.delete(topic)
          disablePointCloudWorker(error)
          updatePointCloud(topic, message)
          applyFixedFrame(topic, message)
        }
      })
    }

    const queuePointCloudUpdate = (topic, message) => {
      pendingPointClouds.set(topic, message)
      schedulePointCloudFlush()
    }

    const refreshMarkerTransforms = (topic) => {
      const group = visualizationObjects.get(topic)
      if (!group?.userData?.markerGroup) return

      const error = refreshMarkerGroupTransforms(group, (marker, object) => {
        const timestamp = markerTransformTimestamp(marker, messageTimestampMs(marker))
        if (applyFixedFrame(topic, marker, object, false, timestamp)) return ''
        const frame = frameIdFromMessage(marker) || 'unknown'
        return `缺少 ${frame} → ${fixedFrameId} 的 TF`
      })
      setDisplayStatus(topic, error)
    }

    const refreshFixedFrameObjects = () => {
      transformFrameRequest = null
      latestDisplayMessages.forEach(({ messageType, message }, topic) => {
        // Hidden/removed Displays are unsubscribed. Their last message may still
        // be cached, but a TF update must never recreate their visualization.
        if (!rosSubscriptions.has(topic)) return
        if ((messageType || '').includes('Odometry')) {
          updateOdometry(topic, message)
        } else if ((messageType || '').includes('Marker')) {
          // Marker 对象在原位重新应用 TF，避免重建对象和重置 lifetime。
          refreshMarkerTransforms(topic)
        } else {
          applyFixedFrame(topic, message)
        }
      })
    }

    const scheduleTransformRefresh = () => {
      if (transformFrameRequest === null) {
        transformFrameRequest = requestAnimationFrame(refreshFixedFrameObjects)
      }
    }

    const transformPoseToFixed = (topic, message, position, orientation) => {
      const sourceFrame = frameIdFromMessage(message)
      if (!sourceFrame || sourceFrame === fixedFrameId.replace(/^\/+/, '')) {
        setDisplayStatus(topic)
        return { position, orientation }
      }
      const transform = tfBuffer.lookupTransform(fixedFrameId, sourceFrame, messageTimestampMs(message))
      if (!transform) {
        setDisplayStatus(topic, `缺少 ${sourceFrame} → ${fixedFrameId} 的 TF`)
        return null
      }
      const poseMatrix = new THREE.Matrix4().compose(
        new THREE.Vector3(Number(position.x || 0), Number(position.y || 0), Number(position.z || 0)),
        new THREE.Quaternion(
          Number(orientation?.x || 0), Number(orientation?.y || 0),
          Number(orientation?.z || 0), Number(orientation?.w ?? 1)
        ).normalize(),
        new THREE.Vector3(1, 1, 1)
      )
      const result = transform.clone().multiply(poseMatrix)
      const nextPosition = new THREE.Vector3()
      const nextOrientation = new THREE.Quaternion()
      result.decompose(nextPosition, nextOrientation, new THREE.Vector3())
      setDisplayStatus(topic)
      return { position: nextPosition, orientation: nextOrientation }
    }

    const isPathLikeMessageType = (messageType = '') => {
      return messageType.includes('Path') || messageType.includes('PositionCommand')
    }

    const isPositionCommandMessage = (topic = '', messageType = '', message = null) => {
      if ((messageType || '').includes('PositionCommand')) return true
      if (topic === '/planning/pos_cmd') return true
      return !!(
        message &&
        message.position &&
        (
          Object.prototype.hasOwnProperty.call(message, 'trajectory_flag') ||
          Object.prototype.hasOwnProperty.call(message, 'trajectory_id')
        )
      )
    }

    const defaultVisualizationTopics = getDefaultVisualizationTopics()
    let defaultVisualizationSubscribed = false

    // 持久化设置存储
    const persistentSettings = {
      laser: {
        showLaserPoints: true,
        showLaserLines: true,
        showIntensity: false,
        pointSize: 0.15
      },
      pointcloud: {
        pointSize: 0.05,
        opacity: 0.8,
        showIntensity: false
      },
      map: {
        showMap: true,
        opacity: 0.8,
        showGrid: true,
        showOrigin: true
      },
      position: {
        showRobotModel: false,
        showTrajectory: true,
        trajectoryLength: 20
      }
    }

    // 地图相关对象
    const mapMesh = ref(null)
    const mapTexture = ref(null)

    // 轨迹记录（用于里程计）
    let trajectoryPoints = []

    // 导航工具状态
    let currentNavigationTool = 'move'
    let fixedFrameId = 'map'
    let positionOdomTopic = ''
    let isDragging = false
    let dragStartPosition = null
    let dragCurrentPosition = null
    let previewArrow = null
    let goalPublishTopic = ''
    let selectedObject = null
    let selectionHelper = null

    // FPS 计算
    let lastTime = 0
    let frameCount = 0
    let fpsTime = 0
    
    /**
     * 初始化 Three.js 场景
     */
    const initScene = async () => {
      try {
        // 创建场景
        scene = new THREE.Scene()
        scene.background = new THREE.Color(getThemeColor('--scene-background'))
        
        // 创建相机 - 设置为俯视XY平面的视角
        const aspect = containerRef.value.clientWidth / containerRef.value.clientHeight
        perspectiveCamera = new THREE.PerspectiveCamera(75, aspect, 0.1, 1000)
        const orthoHeight = 20
        orthographicCamera = new THREE.OrthographicCamera(
          (-orthoHeight * aspect) / 2,
          (orthoHeight * aspect) / 2,
          orthoHeight / 2,
          -orthoHeight / 2,
          0.1,
          1000
        )
        camera = perspectiveCamera
        // Default angled map view: keep world X axis horizontal on screen.
        camera.up.set(0, 0, 1)
        camera.position.set(0, -14, 10)
        camera.lookAt(0, 0, 0)
        
        // 创建渲染器
        renderer = new THREE.WebGLRenderer({ 
          antialias: true,
          alpha: true
        })
        renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
        renderer.setPixelRatio(window.devicePixelRatio)
        renderer.shadowMap.enabled = true
        renderer.shadowMap.type = THREE.PCFSoftShadowMap
        containerRef.value.appendChild(renderer.domElement)

        if (window.ResizeObserver) {
          containerResizeObserver = new ResizeObserver(() => {
            onWindowResize()
          })
          containerResizeObserver.observe(containerRef.value)
        }
        
        // 创建轨道控制器
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
        controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        controls.dampingFactor = 0.05
        controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE
        controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN
        controls.mouseButtons.RIGHT = THREE.MOUSE.NONE
        controls.addEventListener('end', onCameraChange)
        
        // 创建光照
        ambientLight = new THREE.AmbientLight(0x404040, 0.6)
        scene.add(ambientLight)
        
        directionalLight = new THREE.DirectionalLight(0xffffff, 0.8)
        directionalLight.position.set(10, 10, 5)
        directionalLight.castShadow = true
        directionalLight.shadow.mapSize.width = 2048
        directionalLight.shadow.mapSize.height = 2048
        scene.add(directionalLight)
        
        // 创建网格 - 在XY平面上，Z=0，与RViz一致
        // Three.js的GridHelper默认在XZ平面，需要旋转到XY平面
        gridHelper = new THREE.GridHelper(20, 20, 0x888888, 0x444444)
        gridHelper.position.set(0, 0, 0)  // 网格中心在原点
        gridHelper.rotateX(-Math.PI / 2)  // 旋转90度使网格在XY平面
        scene.add(gridHelper)

        // 创建坐标轴 - 与RViz约定一致：X右(红)，Y前(绿)，Z上(蓝)
        // Three.js默认坐标系：X右，Y上，Z前
        // RViz标准坐标系：X前，Y左，Z上
        // 为了与RViz显示一致，我们不旋转坐标轴，直接使用Three.js的默认方向
        axesHelper = new THREE.AxesHelper(2)
        axesHelper.position.set(0, 0, 0)
        scene.add(axesHelper)

        // 添加坐标系标签
        createCoordinateSystemLabels()

        // 创建机器人模型
        createRobotModel()

        // 订阅位置主题以更新机器人模型
        subscribeToPositionTopics()

        // 窗口大小调整监听
        window.addEventListener('resize', onWindowResize)
        
        // 添加调试快捷键
        window.addEventListener('keydown', onKeyDown)
        
        // 开始渲染循环
        animate()
        
        loading.value = false
        setNavigationTool('move')
        debugLog('3D Scene initialized successfully')
        debugLog('坐标系设置：')
        debugLog('- X轴：向前（红色）')
        debugLog('- Y轴：向左（绿色）')
        debugLog('- Z轴：向上（蓝色）')
        debugLog('机器人模型已创建，等待里程计数据...')
        
      } catch (error) {
        console.error('Failed to initialize 3D scene:', error)
        loading.value = false
      }
    }
    
    /**
     * 创建坐标系标签
     */
    const createCoordinateSystemLabels = () => {
      try {
        // 为每个标签创建独立的canvas
        const createLabelSprite = (text, color, position) => {
          const canvas = document.createElement('canvas')
          const context = canvas.getContext('2d')
          canvas.width = 64
          canvas.height = 64

          context.clearRect(0, 0, 64, 64)
          context.fillStyle = color
          context.font = 'Bold 24px Arial'
          context.textAlign = 'center'
          context.fillText(text, 32, 40)

          const texture = new THREE.CanvasTexture(canvas)
          const material = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            alphaTest: 0.01,
            depthTest: false,
            depthWrite: false
          })
          const sprite = new THREE.Sprite(material)
          sprite.renderOrder = 1000
          sprite.position.copy(position)
          sprite.scale.set(0.5, 0.5, 1)
          return sprite
        }

        // X轴标签 (红色) - 水平方向
        const xSprite = createLabelSprite('X', getThemeColor('--axis-x'), new THREE.Vector3(2.5, 0, 0))
        scene.add(xSprite)

        // Y轴标签 (绿色) - 向上方向
        const ySprite = createLabelSprite('Y', getThemeColor('--axis-y'), new THREE.Vector3(0, 2.5, 0))
        scene.add(ySprite)

        // Z轴标签 (蓝色) - 深度方向
        const zSprite = createLabelSprite('Z', getThemeColor('--axis-z'), new THREE.Vector3(0, 0, 2.5))
        scene.add(zSprite)

        debugLog('坐标系标签已创建')
        debugLog('- X轴 (红色): 水平向右')
        debugLog('- Y轴 (绿色): 垂直向上')
        debugLog('- Z轴 (蓝色): 深度向前')
      } catch (error) {
        console.warn('创建坐标系标签失败:', error)
      }
    }

    /**
     * 创建机器人模型
     */
    let robotModel = null
    const createRobotModel = () => {
      try {
        robotModel = new THREE.Group()

        const bodyMaterial = new THREE.MeshLambertMaterial({ color: 0x2e7d32 })
        const armMaterial = new THREE.MeshLambertMaterial({ color: 0x455a64 })
        const rotorMaterial = new THREE.MeshLambertMaterial({ color: 0x90a4ae, transparent: true, opacity: 0.75 })
        const frontRotorMaterial = new THREE.MeshLambertMaterial({ color: 0xff0000, transparent: true, opacity: 0.75 })
        const lidarMaterial = new THREE.MeshLambertMaterial({ color: 0x1e88e5 })
        // Central UAV body, slightly flattened for a clear top-down silhouette.
        const bodyGeometry = new THREE.BoxGeometry(0.55, 0.42, 0.16)
        const body = new THREE.Mesh(bodyGeometry, bodyMaterial)
        body.position.set(0, 0, 0.02)
        robotModel.add(body)

        // X frame: two diagonal arms for a quadrotor top-down silhouette.
        const armGeometry = new THREE.BoxGeometry(1.65, 0.08, 0.06)
        const armA = new THREE.Mesh(armGeometry, armMaterial)
        const armB = new THREE.Mesh(armGeometry, armMaterial)
        armA.position.set(0, 0, 0.02)
        armB.position.set(0, 0, 0.02)
        armA.rotation.z = Math.PI / 4
        armB.rotation.z = -Math.PI / 4
        robotModel.add(armA)
        robotModel.add(armB)

        // Horizontal discs represent the combined motors and propellers.
        const rotorGeometry = new THREE.CylinderGeometry(0.32, 0.32, 0.035, 40)
        const rotorOffset = 0.58
        const rotorPositions = [
          { x: rotorOffset, y: rotorOffset },
          { x: rotorOffset, y: -rotorOffset },
          { x: -rotorOffset, y: rotorOffset },
          { x: -rotorOffset, y: -rotorOffset }
        ]

        rotorPositions.forEach(pos => {
          const isFrontRotor = pos.x > 0
          const material = isFrontRotor ? frontRotorMaterial : rotorMaterial
          const rotor = new THREE.Mesh(rotorGeometry, material)
          rotor.position.set(pos.x, pos.y, 0.04)
          rotor.rotation.x = Math.PI / 2
          robotModel.add(rotor)
        })

        // Small cylinder on top representing the LiDAR.
        const lidarGeometry = new THREE.CylinderGeometry(0.12, 0.12, 0.12, 32)
        const lidar = new THREE.Mesh(lidarGeometry, lidarMaterial)
        lidar.position.set(0, 0, 0.14)
        lidar.rotation.x = Math.PI / 2
        robotModel.add(lidar)

        const robotAxes = new THREE.AxesHelper(0.45)
        robotAxes.position.set(0, 0, 0.16)
        robotModel.add(robotAxes)

        robotModel.position.set(0, 0, 0)
        robotModel.scale.set(0.5, 0.5, 0.5)
        robotModel.userData = {
          type: 'uav',
          lastUpdate: Date.now()
        }
        robotModel.visible = persistentSettings.position.showRobotModel === true

        scene.add(robotModel)
        debugLog('UAV model created')

      } catch (error) {
        console.warn('Failed to create UAV model:', error)
      }
    }

    const updateRobotPosition = (position, orientation = null) => {
      if (!robotModel) return

      try {
        // 更新位置 - 确保使用正确的坐标映射，支持下划线前缀
        // X: 水平 (前后), Y: 水平 (左右), Z: 高度
        const x = Number(position.x ?? 0)
        const y = Number(position.y ?? 0)
        const z = Number(position.z ?? 0)

        robotModel.position.set(x, y, z)

        // 更新方向，支持下划线前缀
        if (orientation) {
          robotModel.quaternion.set(
            Number(orientation.x ?? 0),
            Number(orientation.y ?? 0),
            Number(orientation.z ?? 0),
            Number(orientation.w ?? 1)
          )
        }

        robotModel.userData.lastUpdate = Date.now()
        // debugLog(`[updateRobotPosition] 机器人位置更新: (${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`)

        // 创建轨迹点（基于机器人位置更新）
        if (persistentSettings.position.showTrajectory) {
          const currentPos = new THREE.Vector3(x, y, z)

          // 只在位置变化超过阈值时添加轨迹点
          if (trajectoryPoints.length === 0 ||
              trajectoryPoints[trajectoryPoints.length - 1].distanceTo(currentPos) > 0.1) {
            trajectoryPoints.push(currentPos.clone())
            // debugLog(`[Trajectory-Robot] 添加轨迹点 #${trajectoryPoints.length}: (${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`)

            // 限制轨迹点数量（由控制面板传入，范围10~100）
            const maxLen = Math.max(10, Math.min(100, persistentSettings.position.trajectoryLength || 100))
            if (trajectoryPoints.length > maxLen) {
              trajectoryPoints.shift()
              // debugLog(`[Trajectory-Robot] 轨迹点数量达到上限，移除最早的点`)
            }

            // 创建或更新轨迹线
            if (trajectoryPoints.length > 1) {
              // 清除之前的独立轨迹线
              const existingTrajectory = scene.children.find(child => child.userData?.type === 'global_trajectory')
              if (existingTrajectory) {
                scene.remove(existingTrajectory)
                existingTrajectory.geometry?.dispose()
                existingTrajectory.material?.dispose()
              }

              // 创建新的全局轨迹线
              const globalTrajectoryGeometry = new THREE.BufferGeometry().setFromPoints(trajectoryPoints)
              const globalTrajectoryMaterial = new THREE.LineBasicMaterial({
                color: 0xff0000,  // 红色全局轨迹
                transparent: false,
                linewidth: 6
              })
              const globalTrajectoryLine = new THREE.Line(globalTrajectoryGeometry, globalTrajectoryMaterial)
              globalTrajectoryLine.userData = { type: 'global_trajectory' }
              globalTrajectoryLine.visible = true

              scene.add(globalTrajectoryLine)
              // debugLog(`[Trajectory-Robot] 创建全局轨迹线，点数: ${trajectoryPoints.length}`)
            }
          }
        }

      } catch (error) {
        console.warn('更新机器人位置失败:', error)
      }
    }

    /**
     * 订阅位置主题更新机器人位置 (与位置信息面板保持一致)
     */
    const subscribeToPositionTopics = () => {
      debugLog('[Scene3D] 开始订阅位置主题以更新机器人模型...')

      const positionTopics = getPositionTopics()

      positionTopics.forEach(({ topic, type }) => {
        debugLog(`[Scene3D] 尝试订阅位置主题: ${topic} (${type})`)

        try {
          rosbridge.subscribe(topic, type, (message) => {
            // debugLog(`[Scene3D] 收到${topic}位置数据，更新机器人模型`)

            let position = null
            let orientation = null

            // 根据消息类型解析位置信息
            if (type === 'nav_msgs/msg/Odometry') {
              const pose = message.pose
              if (pose?.pose) {
                position = pose.pose.position
                orientation = pose.pose.orientation
              }
            } else if (type === 'geometry_msgs/msg/PoseStamped') {
              const poseMsg = message.pose
              if (poseMsg) {
                position = poseMsg.position
                orientation = poseMsg.orientation
              }
            } else if (type === 'geometry_msgs/msg/PoseWithCovarianceStamped') {
              const pose = message.pose
              if (pose?.pose) {
                position = pose.pose.position
                orientation = pose.pose.orientation
              }
            }

            // 使用updateRobotPosition函数更新机器人位置
            if (position && topic === positionOdomTopic) {
              updateRobotPosition(position, orientation)
              // 减少频繁的位置更新日志
              // debugLog(`[Scene3D] 机器人位置已更新: (${position.x?.toFixed(3)}, ${position.y?.toFixed(3)}, ${position.z?.toFixed(3)})`)
            } else {
              console.warn(`[Scene3D] 无法从${topic}解析位置信息`, message)
            }
          })

          debugLog(`[Scene3D] ✅ 成功订阅位置主题: ${topic}`)
        } catch (error) {
          console.error(`[Scene3D] 订阅${topic}失败:`, error)
        }
      })
    }


    /**
     * 渲染循环
     */
    const animate = (currentTime = 0) => {
      animationId = requestAnimationFrame(animate)
      
      // 更新控制器
      if (controls) {
        controls.update()
      }

      if (selectionHelper) {
        selectionHelper.update()
      }
      
      // 渲染场景
      if (renderer && scene && camera) {
        renderer.render(scene, camera)
      }
      
      // 计算 FPS
      frameCount++
      fpsTime += currentTime - lastTime
      lastTime = currentTime
      
      if (fpsTime >= 1000) {
        performanceStats.value.fps = Math.round((frameCount * 1000) / fpsTime)
        frameCount = 0
        fpsTime = 0
      }
      
      // 更新对象和顶点数
      if (scene) {
        let objectCount = 0
        let vertexCount = 0
        
        scene.traverse((object) => {
          if (object.isMesh) {
            objectCount++
            if (object.geometry) {
              const positionAttribute = object.geometry.getAttribute('position')
              if (positionAttribute) {
                vertexCount += positionAttribute.count
              }
            }
          }
        })
        
        performanceStats.value.objects = objectCount
        performanceStats.value.vertices = vertexCount
      }
    }
    
    /**
     * 窗口大小调整
     */
    const onWindowResize = () => {
      if (!containerRef.value || !camera || !renderer) return
      
      const width = containerRef.value.clientWidth
      const height = containerRef.value.clientHeight
      if (width <= 0 || height <= 0 || !perspectiveCamera || !orthographicCamera) return
      
      const aspect = width / height
      perspectiveCamera.aspect = aspect
      perspectiveCamera.updateProjectionMatrix()

      const orthoHeight = 20
      orthographicCamera.left = (-orthoHeight * aspect) / 2
      orthographicCamera.right = (orthoHeight * aspect) / 2
      orthographicCamera.top = orthoHeight / 2
      orthographicCamera.bottom = -orthoHeight / 2
      orthographicCamera.updateProjectionMatrix()
      
      renderer.setSize(width, height)
    }
    
    /**
     * 相机变化事件
     */
    const onCameraChange = () => {
      const cameraState = getCameraState()
      if (cameraState) {
        emit('camera-moved', cameraState)
      }
    }

    const pointerRaycaster = (event) => {
      const raycaster = new THREE.Raycaster()
      raycaster.params.Points.threshold = 0.12
      const rect = containerRef.value.getBoundingClientRect()
      const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      )
      raycaster.setFromCamera(mouse, camera)
      return raycaster
    }

    const selectableRoot = (object) => {
      let root = object
      while (root?.parent && root.parent !== scene) root = root.parent
      if (!root || root === gridHelper || root === axesHelper || root === selectionHelper) return null
      if (root === ambientLight || root === directionalLight || root === previewArrow) return null
      if (root === robotModel) return root.visible ? root : null
      for (const visualizationObject of visualizationObjects.values()) {
        if (visualizationObject === root) return root
      }
      return null
    }

    const clearSelection = () => {
      selectedObject = null
      if (selectionHelper) {
        scene?.remove(selectionHelper)
        selectionHelper.geometry?.dispose()
        selectionHelper.material?.dispose()
        selectionHelper = null
      }
    }

    const setRobotModelVisible = (visible) => {
      const nextVisible = visible === true
      persistentSettings.position.showRobotModel = nextVisible
      if (!robotModel) return
      robotModel.visible = nextVisible
      if (!nextVisible && selectedObject === robotModel) {
        clearSelection()
        emit('object-selected', null)
      }
    }

    const setPositionOdomTopic = (topic) => {
      positionOdomTopic = typeof topic === 'string' ? topic.trim() : ''
      if (!positionOdomTopic && robotModel) {
        robotModel.visible = false
      }
    }

    const selectObject = (intersection) => {
      const root = selectableRoot(intersection?.object)
      clearSelection()
      if (!root) {
        emit('object-selected', null)
        return
      }

      selectedObject = root
      selectionHelper = new THREE.BoxHelper(root, 0x00d4ff)
      selectionHelper.name = 'rviz-selection-outline'
      selectionHelper.userData.ignoreSelection = true
      selectionHelper.material.depthTest = false
      selectionHelper.renderOrder = 1000
      scene.add(selectionHelper)
      emit('object-selected', {
        object: root,
        point: intersection.point,
        distance: intersection.distance
      })
    }

    const focusSelection = () => {
      if (!selectedObject || !camera || !controls) {
        systemMessage.info('请先使用选择工具选中对象')
        return false
      }

      const bounds = new THREE.Box3().setFromObject(selectedObject)
      if (bounds.isEmpty()) return false
      const center = bounds.getCenter(new THREE.Vector3())
      const size = bounds.getSize(new THREE.Vector3())
      const radius = Math.max(size.length() / 2, 0.5)
      const direction = camera.position.clone().sub(controls.target).normalize()
      controls.target.copy(center)

      if (camera.isOrthographicCamera) {
        camera.position.copy(center).add(direction.multiplyScalar(Math.max(radius * 2, 10)))
        camera.zoom = Math.max(0.1, Math.min(50, 8 / radius))
        camera.updateProjectionMatrix()
      } else {
        const distance = radius / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
        camera.position.copy(center).add(direction.multiplyScalar(Math.max(distance * 1.35, 2)))
      }
      camera.lookAt(center)
      controls.update()
      return true
    }
    
    /**
     * 鼠标点击事件
     */
    const onMouseDown = (event) => {
      if (event.button === 0) { // 左键点击
        containerRef.value?.focus()
        const raycaster = pointerRaycaster(event)

        // 检查是否使用导航工具
        if (currentNavigationTool === '2d_goal' || currentNavigationTool === '2d_pose') {
          // 与地面相交检测（假设地面在z=0平面）
          const groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0)
          const intersection = new THREE.Vector3()
          if (raycaster.ray.intersectPlane(groundPlane, intersection)) {
            // 开始拖拽以设置方向
            isDragging = true
            dragStartPosition = intersection.clone()
            dragCurrentPosition = intersection.clone()
            event.preventDefault()
          }
          return
        }

        if (currentNavigationTool === 'select') {
          const intersects = raycaster.intersectObjects(
            scene.children.filter(child => child !== selectionHelper && child !== previewArrow),
            true
          )
          selectObject(intersects.find(hit => selectableRoot(hit.object)))
          event.preventDefault()
        }
      }
    }

    /**
     * 鼠标移动事件
     */
    const onMouseMove = (event) => {
      if (isDragging && (currentNavigationTool === '2d_goal' || currentNavigationTool === '2d_pose')) {
        event.preventDefault()

        const raycaster = pointerRaycaster(event)

        const groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0)
        const intersection = new THREE.Vector3()
        if (raycaster.ray.intersectPlane(groundPlane, intersection)) {
          dragCurrentPosition = intersection.clone()

          // 计算方向并更新预览箭头
          if (dragStartPosition) {
            const direction = new THREE.Vector2(
              dragCurrentPosition.x - dragStartPosition.x,
              dragCurrentPosition.y - dragStartPosition.y
            )

            // 只有在拖拽了足够距离时才显示箭头
            if (direction.length() > 0.1) {
              if (!previewArrow) {
                createPreviewArrow(dragStartPosition, direction)
              } else {
                updatePreviewArrow(dragStartPosition, direction)
              }
            }
          }
        }
      }
    }

    /**
     * 鼠标释放事件
     */
    const onMouseUp = () => {
      if (isDragging && (currentNavigationTool === '2d_goal' || currentNavigationTool === '2d_pose')) {
        isDragging = false

        // 清除预览箭头
        clearPreviewArrow()

        if (dragStartPosition && dragCurrentPosition) {
          // 计算方向
          const direction = new THREE.Vector2(
            dragCurrentPosition.x - dragStartPosition.x,
            dragCurrentPosition.y - dragStartPosition.y
          )

          // 只有在拖拽了足够距离时才发布消息
          if (direction.length() > 0.1) {
            // 计算角度（从拖拽方向）
            const yaw = Math.atan2(direction.y, direction.x)

            // 创建四元数
            const orientation = new THREE.Quaternion()
            orientation.setFromAxisAngle(new THREE.Vector3(0, 0, 1), yaw)

            // 发布导航消息
            handleNavigationToolClick(dragStartPosition, {
              x: orientation.x,
              y: orientation.y,
              z: orientation.z,
              w: orientation.w
            })
          } else {
            // 如果拖拽距离太短，使用默认方向
            handleNavigationToolClick(dragStartPosition, { x: 0, y: 0, z: 0, w: 1 })
          }
        }

        dragStartPosition = null
        dragCurrentPosition = null
      }
    }
    
    /**
     * 键盘事件处理（调试用）
     */
    const onKeyDown = (event) => {
      const target = event.target
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable) {
        return
      }

      const isNavigationActive = currentNavigationTool === '2d_goal' || currentNavigationTool === '2d_pose'
      const isSceneFocused = document.activeElement === containerRef.value ||
          containerRef.value?.contains(document.activeElement)

      if (isNavigationActive || isSceneFocused) {
        switch (event.key.toLowerCase()) {
          case 'escape':
            event.preventDefault()
            if (isNavigationActive) cancelNavigationSelection()
            else setNavigationTool('move')
            break
          case 'm':
            event.preventDefault()
            setNavigationTool('move')
            break
          case 's':
            event.preventDefault()
            setNavigationTool('select')
            break
          case 'g':
            event.preventDefault()
            setNavigationTool('2d_goal')
            break
          case 'p':
            event.preventDefault()
            setNavigationTool('2d_pose')
            break
          case 'f':
            event.preventDefault()
            focusSelection()
            break
          case 'd':
            if (import.meta.env.DEV) addDebugInfo()
            break
          case 'r':
            resetCamera()
            break
          case 'c':
            if (import.meta.env.DEV) checkSubscriptionStatus()
            break
        }
      }
    }
    
    const activateCamera = (projection = 'perspective') => {
      const nextCamera = projection === 'orthographic' ? orthographicCamera : perspectiveCamera
      if (!nextCamera || camera === nextCamera) return
      const target = controls?.target.clone() || new THREE.Vector3()
      camera = nextCamera
      if (controls) {
        controls.object = camera
        controls.target.copy(target)
      }
    }

    // 公共方法
    const resetCamera = () => {
      activateCamera('perspective')
      if (camera && controls) {
        // Reset to angled map view while keeping world X horizontal.
        camera.up.set(0, 0, 1)
        camera.position.set(0, -14, 10)
        controls.target.set(0, 0, 0)
        camera.lookAt(controls.target)
        controls.update()
      }
    }
    
    const setGridVisible = (visible) => {
      if (gridHelper) {
        gridHelper.visible = visible
      }
    }
    
    const setAxesVisible = (visible) => {
      if (axesHelper) {
        axesHelper.visible = visible
      }
    }

    const getCameraState = () => {
      if (!camera || !controls) return null
      return {
        position: {
          x: camera.position.x,
          y: camera.position.y,
          z: camera.position.z
        },
        target: {
          x: controls.target.x,
          y: controls.target.y,
          z: controls.target.z
        },
        up: {
          x: camera.up.x,
          y: camera.up.y,
          z: camera.up.z
        },
        zoom: camera.zoom,
        projection: camera.isOrthographicCamera ? 'orthographic' : 'perspective'
      }
    }

    const applyCameraState = (cameraState) => {
      if (!controls || !cameraState?.position || !cameraState?.target) return
      const currentProjection = camera?.isOrthographicCamera ? 'orthographic' : 'perspective'
      activateCamera(cameraState.projection || currentProjection)
      const up = cameraState.up || { x: 0, y: 0, z: 1 }
      camera.up.set(up.x, up.y, up.z)
      camera.position.set(
        cameraState.position.x,
        cameraState.position.y,
        cameraState.position.z
      )
      controls.target.set(
        cameraState.target.x,
        cameraState.target.y,
        cameraState.target.z
      )
      if (Number.isFinite(cameraState.zoom)) {
        camera.zoom = cameraState.zoom
        camera.updateProjectionMatrix()
      }
      camera.lookAt(controls.target)
      controls.update()
    }
    
    const setBackgroundColor = (color) => {
      debugLog('Setting background color to:', color)
      if (scene) {
        try {
          // 支持多种颜色格式
          let threeColor
          if (typeof color === 'string') {
            threeColor = new THREE.Color(color)
          } else if (typeof color === 'number') {
            threeColor = new THREE.Color(color)
          } else if (color && typeof color === 'object' && 'r' in color) {
            threeColor = new THREE.Color(color.r, color.g, color.b)
          } else {
            threeColor = new THREE.Color(color || getThemeColor('--scene-background'))
          }
          
          scene.background = threeColor
          debugLog('Background color updated to:', threeColor.getHexString())
        } catch (error) {
          console.error('Failed to set background color:', error)
          // 设置默认颜色
          scene.background = new THREE.Color(getThemeColor('--scene-background'))
        }
      } else {
        console.warn('Scene not initialized when trying to set background color')
      }
    }
    
    const updateRenderSettings = (settings) => {
      if (renderer) {
        // 更新渲染设置
        if (settings.shadows !== undefined) {
          renderer.shadowMap.enabled = settings.shadows
        }
        if (settings.antialias !== undefined) {
          // 抗锯齿需要重新创建渲染器
        }
      }
      
      if (scene && settings.backgroundColor) {
        scene.background = new THREE.Color(settings.backgroundColor)
      }
    }
    
    // ROS主题订阅方法
    const subscribeToRosTopic = (topicName, messageType) => {
      // debugLog(`[Scene3D] 订阅ROS主题: ${topicName}, 类型: ${messageType}`)
      if (rosSubscriptions.has(topicName)) {
        debugLog(`[Scene3D] 主题已订阅，跳过重复订阅: ${topicName}`)
        return true
      }
      
      try {
        // 使用rosbridge订阅主题
        // debugLog(`[Scene3D] 调用rosbridge.subscribe...`)
        
        const subscription = rosbridge.subscribe(topicName, messageType, (message) => {
          const now = Date.now()
          const subInfo = rosSubscriptions.get(topicName)

          /*
          debugLog(`[Scene3D] 📨 收到主题消息: ${topicName}`, {
            messageType: typeof message,
            hasRanges: message?.ranges?.length,
            hasData: message?.data?.length,
            hasPoints: message?.points?.length,
            messageKeys: message ? Object.keys(message) : []
          })
          */

          if (subInfo) {
            subInfo.messageCount = (subInfo.messageCount || 0) + 1
            subInfo.lastMessageTime = now

            // debugLog(`[Scene3D] 🎉 收到主题 ${topicName} 的第${subInfo.messageCount}条消息`)

            // 确保消息不为空
          if (message) {
              updateVisualization(topicName, messageType, message)
            } else {
              console.warn(`[Scene3D] 收到空消息: ${topicName}`)
            }
          } else {
            console.warn(`[Scene3D] 收到消息但订阅信息不存在: ${topicName}`)
          }
        })
        
        // debugLog(`[Scene3D] rosbridge.subscribe返回:`, subscription)
        
        // 检查订阅是否成功
        if (subscription) {
          // 存储订阅引用和统计信息
          const subscriptionInfo = {
            ...subscription,
            subscribeTime: Date.now(),
            lastMessageTime: 0,
            messageCount: 0,
            topicName,
            messageType
          }
          
          rosSubscriptions.set(topicName, subscriptionInfo)
          // debugLog(`[Scene3D] ✅ 成功订阅主题: ${topicName}, 当前订阅数: ${rosSubscriptions.size}`)
          
          // 设置定时检查，确认是否收到数据
          setTimeout(() => {
            const sub = rosSubscriptions.get(topicName)
            if (sub && sub.messageCount === 0) {
              console.warn(`[Scene3D] ⚠️ 主题 ${topicName} 在 5 秒内没有收到任何消息`)
              systemMessage.warning(`主题 ${topicName} 可能没有数据发布，请检查ROS系统`)
            } else if (sub) {
              // debugLog(`[Scene3D] ✅ 主题 ${topicName} 正常，已收到 ${sub.messageCount} 条消息`)
            }
          }, 5000)
          
          return true
        } else {
          console.error(`[Scene3D] ❌ rosbridge.subscribe返回null/false`)
          systemMessage.error(`订阅主题 ${topicName} 失败`)
          return false
        }
        
      } catch (error) {
        console.error(`[Scene3D] ❌ 订阅主题 ${topicName} 失败:`, error)
        systemMessage.error(`订阅主题 ${topicName} 异常: ${error.message}`)
        return false
      }
    }
    
    // 取消ROS主题订阅
    const unsubscribeFromRosTopic = (topicName) => {
      const subscription = rosSubscriptions.get(topicName)
      latestDisplayMessages.delete(topicName)
      pendingPointClouds.delete(topicName)
      pointCloudDecodesInFlight.delete(topicName)
      if (subscription) {
        try {
          // debugLog(`[Scene3D] 取消订阅主题: ${topicName}`)
          rosbridge.unsubscribe(subscription)
          rosSubscriptions.delete(topicName)
          removeVisualization(topicName)
          // debugLog(`[Scene3D] 已成功取消订阅主题: ${topicName}`)
        } catch (error) {
          console.error(`[Scene3D] 取消订阅主题 ${topicName} 失败:`, error)
        }
      } else {
        console.warn(`[Scene3D] 试图取消不存在的订阅: ${topicName}`)
        // 仍然尝试清除可视化对象
        removeVisualization(topicName)
      }
    }

    const subscribeToDefaultVisualizationTopics = () => {
      if (defaultVisualizationSubscribed) {
        return
      }

      defaultVisualizationSubscribed = true
      defaultVisualizationTopics.forEach(({ topic, type }) => {
        subscribeToRosTopic(topic, type)
      })
      systemMessage.success('已加载 RViz2 默认显示配置')
    }

    const subscribeToTfTopics = () => {
      subscribeToRosTopic('/tf', 'tf2_msgs/msg/TFMessage')
      subscribeToRosTopic('/tf_static', 'tf2_msgs/msg/TFMessage')
    }

    // 取消所有订阅
    const unsubscribeAllTopics = () => {
      // debugLog(`[Scene3D] 取消所有订阅, 当前订阅数: ${rosSubscriptions.size}`)

      rosSubscriptions.forEach((subscription, topicName) => {
        unsubscribeFromRosTopic(topicName)
      })

      clearAllVisualizations()
    }
    
    // 添加更新频率控制
    let lastLogTime = 0
    let messageCount = 0

    const updateVisualization = (topic, messageType, message) => {
      messageCount++
      const now = Date.now()

      // 只每5秒记录一次日志，避免刷屏
      if (now - lastLogTime > 5000) {
        debugLog(`[Scene3D] 📡 处理可视化更新 - 主题: ${topic}, 消息类型: ${messageType}, 最近5秒处理了${messageCount}条消息`)
        lastLogTime = now
        messageCount = 0
      }

      try {
        if (!(messageType || '').includes('TFMessage')) {
          observeMessageFrames(message)
          const cachedMessage = (messageType || '').includes('PointCloud2')
            ? pointCloudTransformMessage(message)
            : message
          latestDisplayMessages.set(topic, { messageType, message: cachedMessage })
        }
        if (isPositionCommandMessage(topic, messageType, message)) {
          debugLog(`[Scene3D] 🔄 处理位置指令轨迹消息...`)
          updatePositionCommandPath(topic, message, messageType || 'mars_quadrotor_msgs/msg/PositionCommand')
          return
        }

        // 根据消息类型更新可视化
        switch (messageType) {
          case 'sensor_msgs/msg/PointCloud2':
          case 'sensor_msgs/PointCloud2':
            queuePointCloudUpdate(topic, message)
            return
          case 'tf2_msgs/msg/TFMessage':
          case 'tf2_msgs/TFMessage':
            tfBuffer.updateMessage(message, topic === '/tf_static')
            emitFrameList()
            applyFollowFrame()
            scheduleTransformRefresh()
            return
          case 'sensor_msgs/msg/LaserScan':
          case 'sensor_msgs/LaserScan':
            debugLog(`[Scene3D] 🔄 处理激光雷达消息...`)
            updateLaserScan(topic, message)
            break
          case 'visualization_msgs/msg/Marker':
          case 'visualization_msgs/Marker':
            debugLog(`[Scene3D] 🔄 处理标记消息...`)
            updateMarker(topic, message)
            break
          case 'visualization_msgs/msg/MarkerArray':
          case 'visualization_msgs/MarkerArray':
            debugLog(`[Scene3D] 🔄 处理标记数组消息...`)
            updateMarkerArray(topic, message)
            break
          case 'nav_msgs/msg/Path':
          case 'nav_msgs/Path':
            debugLog(`[Scene3D] 🔄 处理路径消息...`)
            updatePath(topic, message)
            break
          case 'mars_quadrotor_msgs/msg/PositionCommand':
          case 'mars_quadrotor_msgs/PositionCommand':
            debugLog(`[Scene3D] 🔄 处理位置指令轨迹消息...`)
            updatePositionCommandPath(topic, message, messageType)
            break
          case 'nav_msgs/msg/Odometry':
          case 'nav_msgs/Odometry':
            {
              const pose = message?.pose
              const poseData = pose?.pose
              const position = poseData?.position
              const orientation = poseData?.orientation

              debugLog(`[Scene3D] 🔄 准备处理里程计消息，主题: ${topic}`)
              debugLog(`[Scene3D] 🔄 里程计消息内容预览:`, {
                topic,
                hasMessage: !!message,
                hasHeader: !!message?.header,
                hasPose: !!pose,
                hasPosePose: !!poseData,
                hasPosition: !!position,
                hasOrientation: !!orientation
              })
              updateOdometry(topic, message)
            }
            break
          case 'geometry_msgs/msg/PoseStamped':
          case 'geometry_msgs/PoseStamped':
            debugLog(`[Scene3D] 🔄 处理位置消息...`)
            updatePoseStamped(topic, message)
            break
          case 'geometry_msgs/msg/PoseWithCovarianceStamped':
          case 'geometry_msgs/PoseWithCovarianceStamped':
            debugLog(`[Scene3D] 🔄 处理带协方差位置消息...`)
            updatePoseWithCovarianceStamped(topic, message)
            break
          default:
            console.warn(`[Scene3D] ⚠️ 不支持的消息类型: ${messageType}`)
            return
        }
        
        applyFixedFrame(topic, message)
        
      } catch (error) {
        console.error(`[Scene3D] ❌ 处理可视化消息时发生错误:`, error)
      }
    }
    
    const setVisualizationVisible = (topic, visible) => {
      const object = visualizationObjects.get(topic)
      if (object) {
        object.visible = visible
      }

      const linesObject = visualizationObjects.get(topic + '_lines')
      if (linesObject) {
        linesObject.visible = visible
      }
    }

    const configureDisplay = (topic, config = {}) => {
      if (!topic) return

      const previousConfig = displayConfigs.get(topic) || {}
      const nextConfig = {
        ...previousConfig,
        ...(config || {})
      }
      displayConfigs.set(topic, nextConfig)

      const object = visualizationObjects.get(topic)
      if (!object) return

      if (object.userData?.messageType === 'sensor_msgs/msg/PointCloud2') {
        const renderStyle = nextConfig.renderStyle === 'boxes' ? 'boxes' : 'points'
        const currentStyle = object.userData.renderStyle || 'points'
        const boxSizeChanged = renderStyle === 'boxes' && Number(previousConfig.boxSize) !== Number(nextConfig.boxSize)

        if ((renderStyle !== currentStyle || boxSizeChanged) && object.userData.originalMessage) {
          const message = object.userData.originalMessage
          if (object.userData.decodedPointCloud) {
            updateDecodedPointCloud(topic, message, object.userData.decodedPointCloud)
          } else {
            updatePointCloud(topic, message)
          }
          applyFixedFrame(topic, message)
          return
        }

        if (object.isPoints && object.material && nextConfig.pointSize !== undefined) {
          object.material.size = Number(nextConfig.pointSize) || object.material.size
          object.material.needsUpdate = true
        }
      }

      if (isPathLikeMessageType(object.userData?.messageType || '')) {
        const pathColor = nextConfig.color ? new THREE.Color(nextConfig.color) : null
        const applyPathMaterialConfig = (material) => {
          if (!material) return
          if (pathColor && material.color) {
            material.color = pathColor
          }
          if (nextConfig.lineWidth !== undefined && material.linewidth !== undefined) {
            material.linewidth = Number(nextConfig.lineWidth) || material.linewidth
          }
          material.needsUpdate = true
        }

        applyPathMaterialConfig(object.material)
        object.traverse?.((child) => applyPathMaterialConfig(child.material))
      }

      if ((object.userData?.messageType || '').includes('Marker')) {
        const markerColor = nextConfig.color ? new THREE.Color(nextConfig.color) : null
        const markerOpacity = nextConfig.opacity === undefined
          ? null
          : THREE.MathUtils.clamp(Number(nextConfig.opacity), 0, 1)
        object.traverse?.((child) => {
          const materials = Array.isArray(child.material) ? child.material : [child.material]
          materials.filter(Boolean).forEach(material => {
            if (markerColor && material.color) material.color.copy(markerColor)
            if (markerOpacity !== null) {
              material.opacity = markerOpacity
              material.transparent = markerOpacity < 1
              material.depthWrite = markerOpacity >= 1
            }
            material.needsUpdate = true
          })
        })
      }
    }

    const removeVisualization = (topic) => {
      const markerTimerPrefix = `${topic}\u0000`
      markerLifetimeTimers.forEach((timer, key) => {
        if (key.startsWith(markerTimerPrefix)) {
          clearTimeout(timer)
          markerLifetimeTimers.delete(key)
        }
      })
      const object = visualizationObjects.get(topic)
      if (object) {
        if (selectedObject === object) clearSelection()
        // debugLog(`[Scene3D] 清除可视化对象: ${topic}`)

        // 递归清理对象和其子对象
        const cleanupObject = (obj) => {
          if (obj.geometry) {
            obj.geometry.dispose()
          }
          if (obj.material) {
            if (Array.isArray(obj.material)) {
              obj.material.forEach(mat => mat.dispose())
            } else {
              obj.material.dispose()
            }
          }
          if (obj.children) {
            obj.children.forEach(child => cleanupObject(child))
          }
        }

        cleanupObject(object)
        scene.remove(object)
        visualizationObjects.delete(topic)

        // debugLog(`[Scene3D] 已清除可视化对象: ${topic}, 剩余对象数: ${visualizationObjects.size}`)
      }

      // 同时检查并清除关联的激光连线对象
      const linesObject = visualizationObjects.get(topic + '_lines')
      if (linesObject) {
        // debugLog(`[Scene3D] 清除激光连线对象: ${topic}_lines`)
        const cleanupObject = (obj) => {
          if (obj.geometry) {
            obj.geometry.dispose()
          }
          if (obj.material) {
            if (Array.isArray(obj.material)) {
              obj.material.forEach(mat => mat.dispose())
            } else {
              obj.material.dispose()
            }
          }
        }
        cleanupObject(linesObject)
        scene.remove(linesObject)
        visualizationObjects.delete(topic + '_lines')
      }
    }

    // 清除所有可视化对象（但保留地图）
    const clearAllVisualizations = () => {
      // debugLog(`[Scene3D] 清除所有可视化对象, 当前数量: ${visualizationObjects.size}`)

      // 需要保留的主题类型（地图相关）
      const preservedTopics = new Set()

      visualizationObjects.forEach((object, topic) => {
        // 只保留PGM加载的地图，不保留主题订阅的地图
        if (topic === 'loaded_map') {
          // debugLog(`[Scene3D] 保留PGM加载的地图: ${topic}`)
          preservedTopics.add(topic)
        } else {
          removeVisualization(topic)
        }
      })

      // 清理轨迹点
      trajectoryPoints = []

      // debugLog(`[Scene3D] 已清除可视化对象，保留 ${preservedTopics.size} 个地图对象`)
      systemMessage.info(`已清除可视化对象，保留了 ${preservedTopics.size} 个地图`)
    }
    
    const getPerformanceStats = () => {
      return performanceStats.value
    }
    
    // 可视化更新方法
    // 点云更新计数器
    let pointCloudUpdateCount = 0

    const pointCloudCapacity = (pointCount) => {
      return 2 ** Math.ceil(Math.log2(Math.max(1, pointCount)))
    }

    const pointCloudBounds = (decoded, padding = 0) => {
      const minimum = decoded?.bounds?.minimum
      const maximum = decoded?.bounds?.maximum
      if (!minimum || !maximum) return null
      return new THREE.Box3(
        new THREE.Vector3(minimum[0] - padding, minimum[1] - padding, minimum[2] - padding),
        new THREE.Vector3(maximum[0] + padding, maximum[1] + padding, maximum[2] + padding)
      )
    }

    const applyDecodedBounds = (geometry, decoded, padding = 0) => {
      const box = pointCloudBounds(decoded, padding)
      if (!box) return null
      geometry.boundingBox = box
      const center = box.getCenter(new THREE.Vector3())
      geometry.boundingSphere = new THREE.Sphere(center, center.distanceTo(box.max))
      return box
    }

    const resetPointCloudTransform = (visualization) => {
      visualization.matrixAutoUpdate = true
      visualization.position.set(0, 0, 0)
      visualization.quaternion.identity()
      visualization.scale.set(1, 1, 1)
      visualization.updateMatrix()
      delete visualization.userData.fixedFrameBaseMatrix
    }

    const updatePointCloudMaterial = (material, opacity) => {
      const transparent = opacity < 1.0
      const depthWrite = !transparent
      const renderStateChanged = material.transparent !== transparent ||
        material.depthWrite !== depthWrite
      material.opacity = opacity
      material.transparent = transparent
      material.depthWrite = depthWrite
      if (renderStateChanged) material.needsUpdate = true
    }

    const updateDecodedPointCloud = (topic, message, decoded) => {
      pointCloudUpdateCount++
      if (!decoded || decoded.error || decoded.pointCount <= 0) {
        removeVisualization(topic)
        setDisplayStatus(topic, decoded?.error || '点云为空或数据格式无效')
        return
      }

      const displayConfig = displayConfigs.get(topic) || {}
      const renderStyle = displayConfig.renderStyle === 'boxes' ? 'boxes' : 'points'
      const opacity = persistentSettings.pointcloud.opacity ?? 1.0
      const positions = decoded.positions
      const pointsProcessed = decoded.pointCount
      const box = pointCloudBounds(decoded)
      const size = box
        ? Math.max(
            box.max.x - box.min.x,
            box.max.y - box.min.y,
            box.max.z - box.min.z
          )
        : 1
      let visualization = visualizationObjects.get(topic)

      if (renderStyle === 'points') {
        const canReuse = visualization?.isPoints &&
          visualization.userData?.renderStyle === 'points' &&
          visualization.userData?.pointCapacity >= pointsProcessed

        if (!canReuse) {
          if (visualization) removeVisualization(topic)
          const capacity = pointCloudCapacity(pointsProcessed)
          const geometry = new THREE.BufferGeometry()
          geometry.setAttribute(
            'position',
            new THREE.BufferAttribute(new Float32Array(capacity * 3), 3).setUsage(THREE.DynamicDrawUsage)
          )
          const material = createHeightColoredPointsMaterial({
            sizeAttenuation: true
          })
          visualization = new THREE.Points(geometry, material)
          visualization.userData.pointCapacity = capacity
          scene.add(visualization)
          visualizationObjects.set(topic, visualization)
        }

        const positionAttribute = visualization.geometry.getAttribute('position')
        positionAttribute.array.set(positions, 0)
        positionAttribute.needsUpdate = true
        visualization.geometry.setDrawRange(0, pointsProcessed)
        applyDecodedBounds(visualization.geometry, decoded)
        visualization.material.size = displayConfig.pointSize ||
          persistentSettings.pointcloud.pointSize ||
          Math.max(0.06, size / 300)
        updatePointCloudMaterial(visualization.material, opacity)
      } else {
        const configuredBoxSize = Number(displayConfig.boxSize)
        const boxSize = Number.isFinite(configuredBoxSize) && configuredBoxSize > 0
          ? configuredBoxSize
          : 0.1
        const canReuse = visualization?.isInstancedMesh &&
          visualization.userData?.renderStyle === 'boxes' &&
          visualization.userData?.pointCapacity >= pointsProcessed &&
          visualization.userData?.boxSize === boxSize

        if (!canReuse) {
          if (visualization) removeVisualization(topic)
          const capacity = pointCloudCapacity(pointsProcessed)
          const geometry = new THREE.BoxGeometry(boxSize, boxSize, boxSize)
          const material = createHeightColoredBoxesMaterial({ color: 0xffffff })
          visualization = new THREE.InstancedMesh(geometry, material, capacity)
          visualization.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
          visualization.userData.pointCapacity = capacity
          visualization.userData.boxSize = boxSize
          scene.add(visualization)
          visualizationObjects.set(topic, visualization)
        }

        visualization.count = pointsProcessed
        const instanceMatrix = new THREE.Matrix4()
        for (let index = 0; index < pointsProcessed; index++) {
          const offset = index * 3
          instanceMatrix.makeTranslation(
            positions[offset],
            positions[offset + 1],
            positions[offset + 2]
          )
          visualization.setMatrixAt(index, instanceMatrix)
        }
        visualization.instanceMatrix.needsUpdate = true
        updatePointCloudMaterial(visualization.material, opacity)
        visualization.boundingBox = pointCloudBounds(decoded, boxSize / 2)
        if (visualization.boundingBox) {
          const center = visualization.boundingBox.getCenter(new THREE.Vector3())
          visualization.boundingSphere = new THREE.Sphere(
            center,
            center.distanceTo(visualization.boundingBox.max)
          )
        }
      }

      visualization.userData = {
        ...visualization.userData,
        topic,
        messageType: 'sensor_msgs/msg/PointCloud2',
        renderStyle,
        pointCount: pointsProcessed,
        originalMessage: pointCloudTransformMessage(message),
        decodedPointCloud: decoded
      }
      resetPointCloudTransform(visualization)
      visualization.visible = persistentSettings.laser.showLaserPoints !== undefined
        ? persistentSettings.laser.showLaserPoints
        : true
      setDisplayStatus(topic)

      if (pointCloudUpdateCount <= 3) {
        systemMessage.success(`成功显示点云 ${topic}: ${pointsProcessed} 个点`)
      }
    }

    const updatePointCloud = (topic, message) => {
      pointCloudUpdateCount++

      // 只在前几次或每100次更新时记录详细信息
      const shouldLog = pointCloudUpdateCount <= 3 || pointCloudUpdateCount % 100 === 0

      if (shouldLog) {
        // debugLog(`Updating point cloud for ${topic} (update #${pointCloudUpdateCount})`)
      }
      
      try {
        // 移除旧的点云
        removeVisualization(topic)
        if (message?.error) {
          setDisplayStatus(topic, String(message.error))
          return
        }
        
        // 创建新的点云几何体
        const geometry = new THREE.BufferGeometry()
        const positions = []
        
        let pointsProcessed = 0
        
        // 解析点云数据
        if (message && typeof message === 'object') {
          if (shouldLog) {
            // debugLog('Processing PointCloud2 message')
            debugLog('Fields:', message.fields)
            debugLog('Width:', message.width, 'Height:', message.height, 'Point step:', message.point_step)
          }
          
          // 如果是 PointCloud2 格式
          if (message.fields && message.data) {
            let dataArray = message.data

            if (!(dataArray instanceof Uint8Array)) {
              dataArray = new Uint8Array(dataArray)
            }
            
            const width = message.width || 1
            const height = message.height || 1
            const pointStep = message.point_step || 16
            const rowStep = message.row_step || width * pointStep
            const totalPoints = width * height
            const littleEndian = message.is_bigendian !== true
            const dataView = new DataView(dataArray.buffer, dataArray.byteOffset, dataArray.byteLength)
            
            if (shouldLog) debugLog(`Processing ${totalPoints} points with step ${pointStep}`)

            // 查找XYZ字段的偏移量
            let xOffset = 0, yOffset = 4, zOffset = 8
            if (message.fields && Array.isArray(message.fields)) {
              message.fields.forEach(field => {
                if (shouldLog) debugLog(`Field: ${field.name}, offset: ${field.offset}, datatype: ${field.datatype}`)
                if (field.name === 'x') xOffset = field.offset
                else if (field.name === 'y') yOffset = field.offset
                else if (field.name === 'z') zOffset = field.offset
              })
            }

            if (shouldLog) debugLog(`Using offsets - X: ${xOffset}, Y: ${yOffset}, Z: ${zOffset}`)
            
            // 解析完整点云。不要只取开头一段，否则地图会像被截断。
            const sampleStep = 1
            const hasUsableRowStep = !message.sampled && height > 1 && rowStep >= width * pointStep

            for (let i = 0; i < totalPoints; i += sampleStep) {
              const row = Math.floor(i / width)
              const col = i % width
              const byteIndex = hasUsableRowStep
                ? row * rowStep + col * pointStep
                : i * pointStep
              
              if (byteIndex + Math.max(xOffset, yOffset, zOffset) + 4 <= dataArray.length) {
                try {
                  // 读取XYZ坐标（PointCloud2 常见为32位浮点数）
                  const x = dataView.getFloat32(byteIndex + xOffset, littleEndian)
                  const y = dataView.getFloat32(byteIndex + yOffset, littleEndian)
                  const z = dataView.getFloat32(byteIndex + zOffset, littleEndian)
                  
                  // 验证坐标值
                  if (!isNaN(x) && !isNaN(y) && !isNaN(z) &&
                      isFinite(x) && isFinite(y) && isFinite(z) &&
                      Math.abs(x) < 1000 && Math.abs(y) < 1000 && Math.abs(z) < 1000) {

                    // ROS坐标系转换到Three.js坐标系
                    // ROS: X前，Y左，Z上 -> Three.js: X右，Y上，Z前
                    // 转换：ROS(x,y,z) -> Three.js(x,y,z) 保持不变，因为我们已经旋转了坐标轴
                    positions.push(x, y, z)
                    pointsProcessed++
                  }
                } catch (parseError) {
                  // 忽略单个点的解析错误
                }
              }
            }
            
            if (shouldLog) debugLog(`Successfully processed ${pointsProcessed} points out of ${totalPoints} (sample step: ${sampleStep})`)
          }
          // 如果是简单的点数组格式
          else if (Array.isArray(message.points)) {
            if (shouldLog) debugLog('Processing points array format')
            for (let i = 0; i < Math.min(message.points.length, 5000); i++) {
              const point = message.points[i]
              if (point && typeof point === 'object') {
                const x = point.x || 0
                const y = point.y || 0
                const z = point.z || 0
                
                positions.push(x, y, z)
                pointsProcessed++
              }
            }
          }
        }
        
        // 空数据或解析失败必须显式失败，不能伪造点云误导用户。
        if (pointsProcessed === 0) {
          geometry.dispose()
          removeVisualization(topic)
          setDisplayStatus(topic, '点云为空或数据格式无效')
          return
        }
        
        // 创建点云对象
        if (positions.length > 0) {
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
          
          // 计算边界框以调整点的大小
          geometry.computeBoundingBox()
          const box = geometry.boundingBox
          const size = Math.max(
            box.max.x - box.min.x,
            box.max.y - box.min.y,
            box.max.z - box.min.z
          )
          
          // 每个 Display 可以独立选择高性能点片或真实三维体素。
          const displayConfig = displayConfigs.get(topic) || {}
          const renderStyle = displayConfig.renderStyle === 'boxes' ? 'boxes' : 'points'
          const opacity = persistentSettings.pointcloud.opacity ?? 1.0
          let visualization

          if (renderStyle === 'boxes') {
            const configuredBoxSize = Number(displayConfig.boxSize)
            const boxSize = Number.isFinite(configuredBoxSize) && configuredBoxSize > 0
              ? configuredBoxSize
              : 0.1
            const boxGeometry = new THREE.BoxGeometry(boxSize, boxSize, boxSize)
            // RViz 的体素颜色接近无光照的原色显示。MeshBasicMaterial
            // 避免背光面被场景灯光压暗，同时保留立方体深度和遮挡。
            const boxMaterial = createHeightColoredBoxesMaterial({
              color: 0xffffff,
              opacity,
              transparent: opacity < 1.0,
              depthWrite: opacity >= 1.0
            })
            const boxes = new THREE.InstancedMesh(boxGeometry, boxMaterial, pointsProcessed)
            const instanceMatrix = new THREE.Matrix4()

            for (let i = 0; i < pointsProcessed; i++) {
              const offset = i * 3
              instanceMatrix.makeTranslation(
                positions[offset],
                positions[offset + 1],
                positions[offset + 2]
              )
              boxes.setMatrixAt(i, instanceMatrix)
            }

            boxes.instanceMatrix.needsUpdate = true
            boxes.computeBoundingBox()
            boxes.computeBoundingSphere()
            geometry.dispose()
            visualization = boxes
          } else {
            const material = createHeightColoredPointsMaterial({
              size: displayConfig.pointSize || persistentSettings.pointcloud.pointSize || Math.max(0.06, size / 300),
              sizeAttenuation: true,
              opacity,
              transparent: opacity < 1.0
            })
            visualization = new THREE.Points(geometry, material)
          }

          visualization.userData = {
            topic,
            messageType: 'sensor_msgs/msg/PointCloud2',
            renderStyle,
            pointCount: pointsProcessed,
            originalMessage: message
          }

          // 根据激光设置决定是否显示点云（当作为3D激光时）
          visualization.visible = persistentSettings.laser.showLaserPoints !== undefined
            ? persistentSettings.laser.showLaserPoints
            : true

          scene.add(visualization)
          visualizationObjects.set(topic, visualization)
          
          // 只在首次或特殊情况下调整相机视角，避免频繁变化
          // Keep the startup camera at the configured default view.
          // Users can still press F to fit the point cloud explicitly.
          
          if (shouldLog) {
            debugLog(`✅ Added ${renderStyle} point cloud with ${pointsProcessed} points`)
            debugLog('Bounding box:', box)
          }

          // 只在首次显示成功消息
          if (pointCloudUpdateCount <= 3) {
            systemMessage.success(`成功显示点云 ${topic}: ${pointsProcessed} 个点`)
          }
        } else {
          console.warn('No positions to create point cloud')
          systemMessage.warning(`点云 ${topic} 没有有效的位置数据`)
        }
        
      } catch (error) {
        console.error('Error updating point cloud:', error)
        systemMessage.error(`点云更新失败: ${error.message}`)
        
        // 创建错误指示器
        const geometry = new THREE.BoxGeometry(2, 2, 2)
        const material = new THREE.MeshBasicMaterial({ 
          color: 0xff0000,
          wireframe: true
        })
        const errorBox = new THREE.Mesh(geometry, material)
        errorBox.userData = { topic, error: true, errorMessage: error.message }
        errorBox.position.set(0, 0, 1)
        
        scene.add(errorBox)
        visualizationObjects.set(topic, errorBox)
        
        debugLog('Added error indicator box')
      }
    }
    
    const updateLaserScan = (topic, message) => {
      // debugLog(`[LaserScan] 开始处理激光雷达数据 for ${topic}`)

      let ranges = message.ranges
      const angle_min = message.angle_min
      const angle_max = message.angle_max
      const angle_increment = message.angle_increment
      const range_min = message.range_min
      const range_max = message.range_max
      // 处理ranges字段 - 可能是字符串格式的Python array
      if (typeof ranges === 'string') {
        // debugLog(`[LaserScan] ranges是字符串格式，尝试解析: ${ranges.substring(0, 100)}...`)
        try {
          // 解析Python array格式：array('f', [1.0, 2.0, 3.0, ...])
          const match = ranges.match(/array\('f',\s*\[(.*)\]\)/)
          if (match) {
            const numbersStr = match[1]
            // 分割并解析数字，处理inf和nan
            ranges = numbersStr.split(',').map(str => {
              const trimmed = str.trim()
              if (trimmed === 'inf') return Infinity
              if (trimmed === '-inf') return -Infinity
              if (trimmed === 'nan') return NaN
              return parseFloat(trimmed)
            })
            // 不要在这里过滤无效值！保留所有值以维持角度索引对应关系
            // debugLog(`[LaserScan] 成功解析${ranges.length}个ranges值 (包含${ranges.filter(val => !isFinite(val)).length}个无效值)`)
          } else {
            console.error(`[LaserScan] 无法解析ranges字符串格式: ${ranges}`)
            ranges = []
          }
        } catch (e) {
          console.error(`[LaserScan] 解析ranges字符串失败:`, e)
          ranges = []
        }
      }



      if (angle_min === undefined || angle_max === undefined || angle_increment === undefined) {
        console.error(`[LaserScan] 无效的激光雷达消息: 缺少角度信息`)
        console.error(`[LaserScan] angle_min=${angle_min}, angle_max=${angle_max}, angle_increment=${angle_increment}`)
        return
      }

      // debugLog(`[LaserScan] ✅ 消息验证通过，开始处理 ${ranges.length} 个激光点`)

      removeVisualization(topic)

      const geometry = new THREE.BufferGeometry()
      const positions = []
      const colors = []

      try {
        // 解析激光雷达数据
        if (ranges && Array.isArray(ranges) && ranges.length > 0) {
          const angleMin = angle_min || -Math.PI
          const angleMax = angle_max || Math.PI
          const angleIncrement = angle_increment || (angleMax - angleMin) / ranges.length
          const rangeMin = range_min || 0.0
          const rangeMax = range_max || 100.0

          // 只在第一次更新时显示详细信息
          if (!updateLaserScan._firstLogged) {
            debugLog(`LaserScan info: ${ranges.length} rays`)
            debugLog(`  - 角度范围: ${angleMin.toFixed(3)} 到 ${angleMax.toFixed(3)} 弧度`)
            debugLog(`  - 角度范围: ${(angleMin * 180 / Math.PI).toFixed(1)}° 到 ${(angleMax * 180 / Math.PI).toFixed(1)}°`)
            debugLog(`  - 角度增量: ${angleIncrement.toFixed(6)} 弧度 (${(angleIncrement * 180 / Math.PI).toFixed(3)}°)`)
            debugLog(`  - 距离范围: ${rangeMin} 到 ${rangeMax} 米`)
            debugLog(`  - 角度跨度: ${((angleMax - angleMin) * 180 / Math.PI).toFixed(1)}°`)

            // 检查是否是完整的360度扫描
            const totalAngle = angleMax - angleMin
            if (Math.abs(totalAngle - 2 * Math.PI) < 0.1) {
              debugLog(`  - 这是360度全方位扫描`)
            } else {
              debugLog(`  - 这是${(totalAngle * 180 / Math.PI).toFixed(1)}度扇形扫描`)
            }

            // 计算应该在90度、180度、270度的索引位置
            const index90 = Math.round((Math.PI / 2 - angleMin) / angleIncrement)
            const index180 = Math.round((Math.PI - angleMin) / angleIncrement)
            const index270 = Math.round((3 * Math.PI / 2 - angleMin) / angleIncrement)
            debugLog(`  - 关键角度索引: 90°→${index90}, 180°→${index180}, 270°→${index270}`)

            // 检查这些索引是否有有效数据
            if (index90 >= 0 && index90 < ranges.length) {
              const range90 = ranges[index90]
              debugLog(`  - 90度方向距离: ${range90} (${isFinite(range90) ? '有效' : '无效'})`)
            }
            if (index180 >= 0 && index180 < ranges.length) {
              const range180 = ranges[index180]
              debugLog(`  - 180度方向距离: ${range180} (${isFinite(range180) ? '有效' : '无效'})`)
            }
          }

          let validPoints = 0
          let minX = Infinity, maxX = -Infinity
          let minY = Infinity, maxY = -Infinity
          for (let i = 0; i < ranges.length; i++) {
            const angle = angleMin + i * angleIncrement
            const range = ranges[i]

            // 过滤有效距离值
            if (range >= rangeMin && range <= rangeMax && isFinite(range)) {
              // 极坐标转笛卡尔坐标 - 完全按照flask_ros/map-2d.js的drawLaserScan实现
              // 第730-736行的核心逻辑：
              //
              // const laserAngle = scan.angle_min + index * scan.angle_increment;
              // const worldAngle = this.robotPose.theta + laserAngle;
              // const endX = this.robotPose.x + range * Math.cos(worldAngle);
              // const endY = this.robotPose.y + range * Math.sin(worldAngle);

              // 激光雷达坐标转换 - 修复显示为一条线的问题
              //
              // 问题分析：显示为一条线说明角度计算有问题
              // 让我直接使用标准的极坐标转换，不考虑机器人姿态

              // 极坐标转笛卡尔坐标 - 修复坐标系映射
              // ROS标准：angle_min=-π, angle_max=+π, 0度为前方(+X轴)
              // Three.js坐标系：需要正确映射X/Y/Z轴

              // 方法1：标准ROS坐标系 (先试试这个)
              const x = range * Math.cos(angle)
              const y = range * Math.sin(angle)
              const z = 0

              positions.push(x, y, z)

              // 更新边界框
              minX = Math.min(minX, x)
              maxX = Math.max(maxX, x)
              minY = Math.min(minY, y)
              maxY = Math.max(maxY, y)


              // 改进的颜色方案：更明显的颜色，基于距离
              const normalizedRange = Math.min(Math.max((range - rangeMin) / (rangeMax - rangeMin), 0), 1)

              // 方案1：简单的红绿渐变（近红远绿）
              const red = 1.0 - normalizedRange  // 近距离红色
              const green = normalizedRange      // 远距离绿色
              const blue = 0.2                   // 固定蓝色分量

              colors.push(red, green, blue)

              validPoints++
            }
          }

          // debugLog(`[LaserScan] 处理结果: ${validPoints}/${ranges.length} 有效点`)

          // 详细统计：分析有效点的分布
          if (!updateLaserScan._firstLogged && validPoints > 0) {
            // debugLog(`[LaserScan] 📊 数据分析:`)
            debugLog(`  - 总测量点: ${ranges.length}`)
            debugLog(`  - 有效点数: ${validPoints}`)
            debugLog(`  - 无效点数: ${ranges.length - validPoints}`)
            debugLog(`  - 有效率: ${(validPoints / ranges.length * 100).toFixed(1)}%`)
            debugLog(`  - 角度范围: ${(angleMin * 180 / Math.PI).toFixed(1)}° ~ ${(angleMax * 180 / Math.PI).toFixed(1)}°`)
            debugLog(`  - 距离范围: ${rangeMin}m ~ ${rangeMax}m`)

            // 检查是否真的是360度扫描
            const totalAngleDeg = (angleMax - angleMin) * 180 / Math.PI
            debugLog(`  - 扫描角度跨度: ${totalAngleDeg.toFixed(1)}°`)
            debugLog(`  - 是否360度扫描: ${Math.abs(totalAngleDeg - 360) < 5 ? '是' : '否'}`)

            // 分析有效点的角度分布
            const validAngles = []
            for (let i = 0; i < ranges.length; i++) {
              const range = ranges[i]
              if (range >= rangeMin && range <= rangeMax && isFinite(range)) {
                const angle = angleMin + i * angleIncrement
                validAngles.push(angle * 180 / Math.PI)
              }
            }
            if (validAngles.length > 0) {
              const minAngle = Math.min(...validAngles)
              const maxAngle = Math.max(...validAngles)
              debugLog(`  - 有效点角度分布: ${minAngle.toFixed(1)}° ~ ${maxAngle.toFixed(1)}°`)
              debugLog(`  - 角度分布跨度: ${(maxAngle - minAngle).toFixed(1)}°`)
            }
          }

          // 只在第一次更新时显示边界框信息
          if (!updateLaserScan._firstLogged && validPoints > 0) {
            // debugLog(`[LaserScan] 点云边界框: X=[${minX.toFixed(2)}, ${maxX.toFixed(2)}], Y=[${minY.toFixed(2)}, ${maxY.toFixed(2)}]`)
            // debugLog(`[LaserScan] 点云尺寸: ${(maxX - minX).toFixed(2)}m x ${(maxY - minY).toFixed(2)}m`)
            // debugLog(`[LaserScan] X范围: ${(maxX - minX).toFixed(2)}m, Y范围: ${(maxY - minY).toFixed(2)}m`)

            // 如果Y范围太小，说明有问题
            if ((maxY - minY) < 1.0) {
              console.warn(`[LaserScan] ⚠️ Y坐标范围太小 (${(maxY - minY).toFixed(2)}m)，可能存在解析问题`)
            }
          }

          if (validPoints === 0) {
            console.warn('[LaserScan] 没有找到有效的激光雷达点')
            systemMessage.warning(`激光雷达 ${topic} 没有有效数据点`)

            // 创建一个警告指示器
            const warningGeometry = new THREE.SphereGeometry(0.1, 8, 8)
            const warningMaterial = new THREE.MeshBasicMaterial({ color: 0xffff00 })
            const warningSphere = new THREE.Mesh(warningGeometry, warningMaterial)
            warningSphere.position.set(0, 0, 0.5)
            warningSphere.userData = { topic, messageType: 'sensor_msgs/msg/LaserScan', warning: 'no_valid_points' }
            scene.add(warningSphere)
            visualizationObjects.set(topic, warningSphere)
            return
          }
        } else {
          console.error('[LaserScan] 无效的激光雷达消息格式')
          console.error('[LaserScan] 消息内容:', message)
          systemMessage.error(`激光雷达 ${topic} 消息格式无效`)
          return
        }

        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))

        // 创建激光点对象，应用持久化设置
        const pointMaterial = new THREE.PointsMaterial({
          size: persistentSettings.laser.pointSize || 0.15,
          vertexColors: persistentSettings.laser.showIntensity,
          sizeAttenuation: false,  // 不根据距离缩放，保持固定大小
          alphaTest: 0.5
        })

        const laserPoints = new THREE.Points(geometry, pointMaterial)
        laserPoints.userData = {
          topic,
          messageType: 'sensor_msgs/msg/LaserScan',
          type: 'laser_points',
          pointCount: positions.length / 3
        }
        laserPoints.visible = persistentSettings.laser.showLaserPoints

        // 创建激光连线对象
        const lineGeometry = new THREE.BufferGeometry()
        const linePositions = []

        // 创建从原点到每个激光点的连线
        for (let i = 0; i < positions.length; i += 3) {
          // 原点到激光点的线段
          linePositions.push(0, 0, 0)  // 原点
          linePositions.push(positions[i], positions[i + 1], positions[i + 2])  // 激光点
        }

        lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3))

        const lineMaterial = new THREE.LineBasicMaterial({
          color: 0x00ff00,
          opacity: 0.3,
          transparent: true
        })

        const laserLines = new THREE.LineSegments(lineGeometry, lineMaterial)
        laserLines.userData = {
          topic,
          messageType: 'sensor_msgs/msg/LaserScan',
          type: 'laser_lines',
          pointCount: positions.length / 3
        }
        laserLines.visible = persistentSettings.laser.showLaserLines

        scene.add(laserPoints)
        scene.add(laserLines)

        // 用点对象作为主要的可视化对象存储
        visualizationObjects.set(topic, laserPoints)
        visualizationObjects.set(topic + '_lines', laserLines)

        // 只在第一次成功时显示详细日志和消息
        if (!updateLaserScan._firstLogged) {
          // debugLog(`[LaserScan] 成功添加激光雷达点云: ${positions.length / 3} 个点`)
          systemMessage.success(`激光雷达 ${topic} 显示成功: ${positions.length / 3} 个点`)
          updateLaserScan._firstLogged = true
        }

      } catch (error) {
        console.error('Error updating laser scan:', error)
        systemMessage.error(`激光雷达更新失败: ${error.message}`)
      }
    }
    
    const markerMaterial = (message, displayConfig) => {
      const messageOpacity = message.color?.a ?? 1
      const opacity = displayConfig.opacity === undefined
        ? messageOpacity
        : THREE.MathUtils.clamp(Number(displayConfig.opacity), 0, 1)
      const markerColor = displayConfig.color
        ? new THREE.Color(displayConfig.color)
        : new THREE.Color(
          message.color?.r ?? 1,
          message.color?.g ?? 0,
          message.color?.b ?? 0
        )
      return new THREE.MeshLambertMaterial({
        color: markerColor,
        transparent: opacity < 1,
        opacity,
        depthWrite: opacity >= 1
      })
    }

    const markerPoints = (message) => (message.points || []).map(point => (
      new THREE.Vector3(point?.x ?? 0, point?.y ?? 0, point?.z ?? 0)
    ))

    const applyMarkerPose = (object, message, applyScale = false) => {
      if (message.pose) {
        object.position.set(
          message.pose.position?.x ?? 0,
          message.pose.position?.y ?? 0,
          message.pose.position?.z ?? 0
        )
        if (message.pose.orientation) {
          const orientation = new THREE.Quaternion(
            message.pose.orientation.x ?? 0,
            message.pose.orientation.y ?? 0,
            message.pose.orientation.z ?? 0,
            message.pose.orientation.w ?? 1
          )
          if (orientation.lengthSq() > Number.EPSILON) {
            object.quaternion.copy(orientation.normalize())
          } else {
            object.quaternion.identity()
          }
        }
      }
      if (applyScale && message.scale) {
        object.scale.set(
          message.scale.x ?? 1,
          message.scale.y ?? 1,
          message.scale.z ?? 1
        )
      }
    }

    const createMarkerObject = (message, displayConfig) => {
      const material = markerMaterial(message, displayConfig)
      const points = markerPoints(message)
      let object = null
      let applyScale = false

      switch (message.type) {
        case 0: { // ARROW
          const usesPointEndpoints = points.length >= 2
          const start = points[0] || new THREE.Vector3()
          const end = points[1] || new THREE.Vector3(message.scale?.x ?? 1, 0, 0)
          const direction = end.clone().sub(start)
          const length = Math.max(direction.length(), 0.0001)
          const headLength = usesPointEndpoints
            ? (message.scale?.z ?? Math.min(length * 0.25, 0.3))
            : Math.min(length * 0.25, 0.3)
          const headWidth = usesPointEndpoints
            ? (message.scale?.y ?? Math.min(length * 0.12, 0.15))
            : (message.scale?.z ?? Math.min(length * 0.12, 0.15))
          const arrow = new THREE.ArrowHelper(
            direction.normalize(),
            start,
            length,
            material.color.getHex(),
            headLength,
            headWidth
          )
          arrow.traverse(child => {
            if (child.material) {
              child.material.transparent = material.opacity < 1
              child.material.opacity = material.opacity
              child.material.depthWrite = material.opacity >= 1
            }
          })
          // ArrowHelper 自身的 position 表示端点起点，直接应用 Marker pose
          // 会覆盖它；使用外层 Group 才能正确组合局部端点和 Marker pose。
          object = new THREE.Group()
          object.add(arrow)
          material.dispose()
          break
        }
        case 1: // CUBE
          object = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material)
          applyScale = true
          break
        case 2: // SPHERE
          object = new THREE.Mesh(new THREE.SphereGeometry(0.5, 24, 16), material)
          applyScale = true
          break
        case 3: { // CYLINDER，ROS 轴向为 Z
          const geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 24)
          geometry.rotateX(Math.PI / 2)
          object = new THREE.Mesh(geometry, material)
          applyScale = true
          break
        }
        case 4: // LINE_STRIP
        case 5: { // LINE_LIST
          const lineColor = material.color.clone()
          const lineOpacity = material.opacity
          material.dispose()
          const geometry = new THREE.BufferGeometry().setFromPoints(points)
          const lineMaterial = new THREE.LineBasicMaterial({
            color: lineColor,
            transparent: lineOpacity < 1,
            opacity: lineOpacity,
            linewidth: message.scale?.x ?? 1
          })
          object = message.type === 4
            ? new THREE.Line(geometry, lineMaterial)
            : new THREE.LineSegments(geometry, lineMaterial)
          break
        }
        case 6: // CUBE_LIST
        case 7: { // SPHERE_LIST
          object = new THREE.Group()
          const geometry = message.type === 6
            ? new THREE.BoxGeometry(
              message.scale?.x ?? 1,
              message.scale?.y ?? 1,
              message.scale?.z ?? 1
            )
            : new THREE.SphereGeometry(0.5, 16, 12).scale(
              message.scale?.x ?? 1,
              message.scale?.y ?? 1,
              message.scale?.z ?? 1
            )
          points.forEach(point => {
            const item = new THREE.Mesh(geometry.clone(), material.clone())
            item.position.copy(point)
            object.add(item)
          })
          geometry.dispose()
          material.dispose()
          break
        }
        case 8: { // POINTS
          const color = material.color.clone()
          const opacity = material.opacity
          material.dispose()
          object = new THREE.Points(
            new THREE.BufferGeometry().setFromPoints(points),
            new THREE.PointsMaterial({
              color,
              size: Math.max(message.scale?.x ?? 0.05, 0.001),
              transparent: opacity < 1,
              opacity
            })
          )
          break
        }
        case 9: { // TEXT_VIEW_FACING
          const canvas = document.createElement('canvas')
          const context = canvas.getContext('2d')
          canvas.width = 512
          canvas.height = 128
          context.clearRect(0, 0, canvas.width, canvas.height)
          context.fillStyle = `#${material.color.getHexString()}`
          context.font = '64px sans-serif'
          context.textAlign = 'center'
          context.textBaseline = 'middle'
          context.fillText(String(message.text || ''), 256, 64)
          const texture = new THREE.CanvasTexture(canvas)
          const opacity = material.opacity
          material.dispose()
          object = new THREE.Sprite(new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            opacity
          }))
          const height = Math.max(message.scale?.z ?? 1, 0.001)
          object.scale.set(height * 4, height, 1)
          break
        }
        case 11: { // TRIANGLE_LIST
          const geometry = new THREE.BufferGeometry().setFromPoints(points)
          geometry.computeVertexNormals()
          object = new THREE.Mesh(geometry, material)
          break
        }
        default:
          material.dispose()
          return null
      }

      applyMarkerPose(object, message, applyScale)
      return object
    }

    const disposeMarkerObject = (object) => {
      object.traverse?.(child => {
        child.geometry?.dispose?.()
        const materials = Array.isArray(child.material)
          ? child.material
          : [child.material]
        materials.filter(Boolean).forEach(material => {
          material.map?.dispose?.()
          material.dispose?.()
        })
      })
    }

    const markerKey = (message) => `${message.ns || ''}:${message.id ?? 0}`
    const markerTimerKey = (topic, key) => `${topic}\u0000${key}`

    const clearMarkerGroup = (topic, group) => {
      group.children.slice().forEach(child => {
        group.remove(child)
        disposeMarkerObject(child)
      })
      const prefix = `${topic}\u0000`
      markerLifetimeTimers.forEach((timer, key) => {
        if (key.startsWith(prefix)) {
          clearTimeout(timer)
          markerLifetimeTimers.delete(key)
        }
      })
    }

    const updateMarker = (
      topic,
      message,
      displayConfig = displayConfigs.get(topic) || {},
      reportStatus = true
    ) => {
      const reportMarkerStatus = (error = '') => {
        if (reportStatus) setDisplayStatus(topic, error)
        return error
      }
      let group = visualizationObjects.get(topic)
      if (!group || group.userData?.markerGroup !== true) {
        removeVisualization(topic)
        group = new THREE.Group()
        group.userData = {
          topic,
          messageType: 'visualization_msgs/msg/Marker',
          markerGroup: true,
          fixedFrameApplied: true
        }
        scene.add(group)
        visualizationObjects.set(topic, group)
      }

      if (message.action === 3) { // DELETEALL
        clearMarkerGroup(topic, group)
        return reportMarkerStatus()
      }

      const key = markerKey(message)
      const timerKey = markerTimerKey(topic, key)
      const existing = group.children.find(child => child.userData?.markerKey === key)
      if (existing) {
        group.remove(existing)
        disposeMarkerObject(existing)
      }
      if (markerLifetimeTimers.has(timerKey)) {
        clearTimeout(markerLifetimeTimers.get(timerKey))
        markerLifetimeTimers.delete(timerKey)
      }
      if (message.action === 2) { // DELETE
        return reportMarkerStatus()
      }

      const object = createMarkerObject(message, displayConfig)
      if (!object) {
        return reportMarkerStatus(`暂不支持 Marker 类型 ${message.type}`)
      }
      object.userData.markerKey = key
      object.userData.messageType = 'visualization_msgs/msg/Marker'
      object.userData.originalMessage = message
      let transformError = ''
      const transformTimestamp = markerTransformTimestamp(
        message,
        messageTimestampMs(message)
      )
      if (!applyFixedFrame(topic, message, object, false, transformTimestamp)) {
        const frame = frameIdFromMessage(message) || 'unknown'
        transformError = `缺少 ${frame} → ${fixedFrameId} 的 TF`
      }
      group.add(object)

      const lifetimeMs = markerLifetimeMilliseconds(message)
      if (lifetimeMs > 0) {
        markerLifetimeTimers.set(timerKey, setTimeout(() => {
          if (object.parent === group) {
            group.remove(object)
            disposeMarkerObject(object)
          }
          markerLifetimeTimers.delete(timerKey)
        }, lifetimeMs))
      }
      return reportMarkerStatus(transformError)
    }

    const updateMarkerArray = (topic, message) => {
      const displayConfig = displayConfigs.get(topic) || {}
      if (!Array.isArray(message.markers)) {
        setDisplayStatus(topic, 'MarkerArray 缺少 markers 数组')
        return
      }
      let firstError = ''
      message.markers.forEach(marker => {
        const error = updateMarker(topic, marker, displayConfig, false)
        if (!firstError && error) firstError = error
      })
      const group = visualizationObjects.get(topic)
      if (group) {
        group.userData.messageType = 'visualization_msgs/msg/MarkerArray'
      }
      setDisplayStatus(topic, firstError)
    }
    
    const updatePath = (topic, message) => {
      // 路径可视化实现
      // debugLog(`Updating path for ${topic}:`, message)
      
      removeVisualization(topic)
      
      const points = []
      
      if (message.poses && message.poses.length > 0) {
        message.poses.forEach(pose => {
          points.push(new THREE.Vector3(
            pose.pose.position?.x || 0,
            pose.pose.position?.y || 0,
            pose.pose.position?.z || 0
          ))
        })
      }
      
      const displayConfig = displayConfigs.get(topic) || {}
      const geometry = new THREE.BufferGeometry().setFromPoints(points)
      const material = new THREE.LineBasicMaterial({
        color: displayConfig.color || 0x00ff00,
        linewidth: displayConfig.lineWidth || 2
      })
      const path = new THREE.Line(geometry, material)
      
      path.userData = { topic, messageType: 'nav_msgs/msg/Path' }
      
      scene.add(path)
      visualizationObjects.set(topic, path)
    }

    const getPositionCommandPoint = (message) => {
      const position = message?.position
      if (!position) return null

      const x = Number(position.x ?? 0)
      const y = Number(position.y ?? 0)
      const z = Number(position.z ?? 0)

      if (![x, y, z].every(Number.isFinite)) return null
      return new THREE.Vector3(x, y, z)
    }

    const updatePositionCommandPath = (topic, message, messageType = 'mars_quadrotor_msgs/msg/PositionCommand') => {
      const point = getPositionCommandPoint(message)
      if (!point) {
        console.warn('[Scene3D] Invalid PositionCommand message format:', {
          topic,
          keys: message ? Object.keys(message) : []
        })
        return
      }

      const points = positionCommandPaths.get(topic) || []
      const lastPoint = points[points.length - 1]
      if (!lastPoint || lastPoint.distanceTo(point) > 0.001) {
        points.push(point)
      }
      if (points.length > 1000) {
        points.splice(0, points.length - 1000)
      }
      positionCommandPaths.set(topic, points)

      removeVisualization(topic)

      const displayConfig = displayConfigs.get(topic) || {}
      const color = displayConfig.color || 0x00ff00
      const geometry = new THREE.BufferGeometry().setFromPoints(points)
      const material = new THREE.LineBasicMaterial({
        color,
        linewidth: displayConfig.lineWidth || 2,
        depthTest: false
      })
      const path = new THREE.Line(geometry, material)
      const currentPointGeometry = new THREE.SphereGeometry(displayConfig.pointSize || 0.12, 12, 12)
      const currentPointMaterial = new THREE.MeshBasicMaterial({ color, depthTest: false })
      const currentPoint = new THREE.Mesh(currentPointGeometry, currentPointMaterial)
      currentPoint.position.copy(point)

      const group = new THREE.Group()
      group.add(path)
      group.add(currentPoint)
      group.userData = { topic, messageType }
      group.renderOrder = 10

      scene.add(group)
      visualizationObjects.set(topic, group)
    }
    

    const updateOdometry = (topic, message) => {
      // debugLog(`[updateOdometry] ⚙️ 开始处理里程计消息 - 主题: ${topic}`)
      // debugLog(`[updateOdometry] 消息内容:`, message)

      try {
        removeVisualization(topic)

        const pose = message?.pose
        const poseData = pose?.pose
        const position = poseData?.position
        const orientation = poseData?.orientation

        if (!position) {
          console.warn('[Scene3D] Invalid odometry message format:', {
            topic,
            keys: message ? Object.keys(message) : [],
            poseKeys: pose ? Object.keys(pose) : [],
            poseDataKeys: poseData ? Object.keys(poseData) : []
          })
          return
        }

        if (topic === positionOdomTopic) {
          const transformedPose = transformPoseToFixed(topic, message, position, orientation)
          if (!transformedPose) return
          updateRobotPosition(transformedPose.position, transformedPose.orientation)
        }

        // Odom from the position panel drives the UAV model itself. Do not draw
        // an extra odom arrow here; it can visually cover the aircraft model.

      } catch (error) {
        console.error('Error updating odometry:', error)
      }
    }

    const updatePoseStamped = (topic, message) => {
      debugLog(`Updating pose stamped for ${topic}:`, message)

      try {
        removeVisualization(topic)

        if (!message.pose || !message.pose.position) {
          console.warn('Invalid pose stamped message format')
          return
        }

        const position = message.pose.position
        const orientation = message.pose.orientation

        if (topic === positionOdomTopic) {
          updateRobotPosition(position, orientation)
        }

        // 创建位置指示器（坐标轴）
        const axesHelper = new THREE.AxesHelper(1)
        axesHelper.position.set(position.x, position.y, position.z)

        if (orientation) {
          axesHelper.quaternion.set(orientation.x, orientation.y, orientation.z, orientation.w)
        }

        axesHelper.userData = {
          topic,
          messageType: 'geometry_msgs/msg/PoseStamped',
          position: { x: position.x, y: position.y, z: position.z }
        }

        scene.add(axesHelper)
        visualizationObjects.set(topic, axesHelper)

        // debugLog(`Successfully updated pose at (${position.x.toFixed(2)}, ${position.y.toFixed(2)}, ${position.z.toFixed(2)})`)

      } catch (error) {
        console.error('Error updating pose stamped:', error)
      }
    }

    const updatePoseWithCovarianceStamped = (topic, message) => {
      debugLog(`Updating pose with covariance for ${topic}:`, message)

      try {
        removeVisualization(topic)

        if (!message.pose || !message.pose.pose || !message.pose.pose.position) {
          console.warn('Invalid pose with covariance message format')
          return
        }

        const position = message.pose.pose.position
        const orientation = message.pose.pose.orientation
        const covariance = message.pose.covariance

        // 创建位置指示器
        const axesHelper = new THREE.AxesHelper(1)
        axesHelper.position.set(position.x, position.y, position.z)

        if (orientation) {
          axesHelper.quaternion.set(orientation.x, orientation.y, orientation.z, orientation.w)
        }

        // 创建协方差椭圆（显示不确定性）
        let uncertaintyEllipse = null
        if (covariance && covariance.length >= 36) {
          // 提取XY平面的协方差
          const cov_xx = covariance[0]   // 第1行第1列
          const cov_yy = covariance[7]   // 第2行第2列
          const cov_xy = covariance[1]   // 第1行第2列

          // 计算椭圆参数
          const trace = cov_xx + cov_yy
          const det = cov_xx * cov_yy - cov_xy * cov_xy

          if (det > 0 && trace > 0) {
            const lambda1 = (trace + Math.sqrt(trace * trace - 4 * det)) / 2
            const lambda2 = (trace - Math.sqrt(trace * trace - 4 * det)) / 2

            const a = Math.sqrt(Math.abs(lambda1)) * 2  // 95%置信间隔
            const b = Math.sqrt(Math.abs(lambda2)) * 2

            // 创建椭圆几何体
            const ellipseGeometry = new THREE.RingGeometry(0, Math.max(a, b), 32)
            const ellipseMaterial = new THREE.MeshBasicMaterial({
              color: 0xff0000,
              transparent: true,
              opacity: 0.3,
              side: THREE.DoubleSide
            })
            uncertaintyEllipse = new THREE.Mesh(ellipseGeometry, ellipseMaterial)
            uncertaintyEllipse.position.set(position.x, position.y, position.z + 0.01)
            uncertaintyEllipse.scale.set(a/Math.max(a,b), b/Math.max(a,b), 1)

            // 旋转椭圆到正确方向
            if (cov_xy !== 0) {
              const angle = 0.5 * Math.atan2(2 * cov_xy, cov_xx - cov_yy)
              uncertaintyEllipse.rotateZ(angle)
            }
          }
        }

        // 组合所有元素
        const group = new THREE.Group()
        group.add(axesHelper)
        if (uncertaintyEllipse) {
          group.add(uncertaintyEllipse)
        }

        group.userData = {
          topic,
          messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
          position: { x: position.x, y: position.y, z: position.z },
          hasCovariance: uncertaintyEllipse !== null
        }

        scene.add(group)
        visualizationObjects.set(topic, group)

        // debugLog(`Successfully updated pose with covariance at (${position.x.toFixed(2)}, ${position.y.toFixed(2)}, ${position.z.toFixed(2)})`)

      } catch (error) {
        console.error('Error updating pose with covariance:', error)
      }
    }

    // 消息验证相关变量
    let verificationSubscriptions = new Map()

    // 启动消息验证
    const startMessageVerification = () => {
      debugLog('[Verification] 启动消息验证系统')

      if (ROS_TOPICS.expectedControl) {
        try {
          const goalPoseVerification = rosbridge.subscribe(ROS_TOPICS.expectedControl, 'geometry_msgs/msg/PoseStamped', (message) => {
            debugLog(`[Verification] ✅ 收到${ROS_TOPICS.expectedControl}消息:`, message)
            systemMessage.success('验证成功：收到发布的目标点消息')
          })

          if (goalPoseVerification) {
            verificationSubscriptions.set(ROS_TOPICS.expectedControl, goalPoseVerification)
            debugLog(`[Verification] ✅ 成功订阅${ROS_TOPICS.expectedControl}用于验证`)
          }
        } catch (error) {
          console.error(`[Verification] 订阅${ROS_TOPICS.expectedControl}失败:`, error)
        }
      }

      if (ROS_TOPICS.initialPose) {
        try {
          const initialPoseVerification = rosbridge.subscribe(ROS_TOPICS.initialPose, 'geometry_msgs/msg/PoseWithCovarianceStamped', (message) => {
            debugLog(`[Verification] ✅ 收到${ROS_TOPICS.initialPose}消息:`, message)
            systemMessage.success('验证成功：收到发布的位置估计消息')
          })

          if (initialPoseVerification) {
            verificationSubscriptions.set(ROS_TOPICS.initialPose, initialPoseVerification)
            debugLog(`[Verification] ✅ 成功订阅${ROS_TOPICS.initialPose}用于验证`)
          }
        } catch (error) {
          console.error(`[Verification] 订阅${ROS_TOPICS.initialPose}失败:`, error)
        }
      }
    }

    // 停止消息验证
    const stopMessageVerification = () => {
      debugLog('[Verification] 停止消息验证系统')
      verificationSubscriptions.forEach((subscription, topic) => {
        try {
          rosbridge.unsubscribe(subscription)
          // debugLog(`[Verification] 取消订阅验证话题: ${topic}`)
        } catch (error) {
          console.error(`[Verification] 取消订阅${topic}失败:`, error)
        }
      })
      verificationSubscriptions.clear()
    }

    // 生命周期
    onMounted(async () => {
      debugLog('Scene3D component mounted')
      await nextTick()

      if (containerRef.value) {
        debugLog('Container found, initializing scene...')
        debugLog('Container size:', containerRef.value.clientWidth, 'x', containerRef.value.clientHeight)

        // 确保容器有尺寸后再初始化
        if (containerRef.value.clientWidth > 0 && containerRef.value.clientHeight > 0) {
          await initScene()
        } else {
          debugLog('Container has no size, retrying in 100ms')
          setTimeout(async () => {
            if (containerRef.value && containerRef.value.clientWidth > 0) {
              await initScene()
            }
          }, 100)
        }
      } else {
        console.error('Container not found!')
      }

      // 检查ROS连接状态并启动验证
      if (rosbridge.isConnected) {
        debugLog('[Scene3D] ROS已连接，启动消息验证')
        startMessageVerification()
        subscribeToDefaultVisualizationTopics()
        subscribeToTfTopics()
      } else {
        debugLog('[Scene3D] ROS未连接，等待连接后启动验证')
        // 定期检查连接状态
        const connectionCheckInterval = setInterval(() => {
          if (rosbridge.isConnected) {
            debugLog('[Scene3D] ROS连接成功，启动消息验证')
            startMessageVerification()
            subscribeToDefaultVisualizationTopics()
            subscribeToTfTopics()
            clearInterval(connectionCheckInterval)
          }
        }, 1000)

        // 1分钟后停止检查
        setTimeout(() => {
          clearInterval(connectionCheckInterval)
        }, 60000)
      }
    })
    
    onUnmounted(() => {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop()
      releaseRecordingStream()
      // 清理资源
      if (animationId) {
        cancelAnimationFrame(animationId)
      }
      if (pointCloudFrameRequest !== null) cancelAnimationFrame(pointCloudFrameRequest)
      if (transformFrameRequest !== null) cancelAnimationFrame(transformFrameRequest)
      pointCloudWorker?.terminate()
      pointCloudWorker = null
      pointCloudDecodesInFlight.clear()
      pendingPointClouds.clear()

      // 停止消息验证
      stopMessageVerification()
      
      window.removeEventListener('resize', onWindowResize)
      window.removeEventListener('keydown', onKeyDown)
      containerResizeObserver?.disconnect()
      containerResizeObserver = null
      clearSelection()
      
      // 清理所有ROS订阅
      rosSubscriptions.forEach((subscription, topicName) => {
        try {
          rosbridge.unsubscribe(subscription)
          // debugLog(`清理ROS订阅: ${topicName}`)
        } catch (error) {
          console.error(`清理ROS订阅失败: ${topicName}`, error)
        }
      })
      rosSubscriptions.clear()
      
      if (controls) {
        controls.dispose()
      }
      
      if (renderer) {
        renderer.dispose()
      }
      
      // 清理几何体和材质
      visualizationObjects.forEach(object => {
        if (object.geometry) {
          object.geometry.dispose()
        }
        if (object.material) {
          if (Array.isArray(object.material)) {
            object.material.forEach(material => material.dispose())
          } else {
            object.material.dispose()
          }
        }
      })
    })

    // 新增控制方法
    const updateRobotTrajectory = () => {
      // 更新所有机器人位姿对象的轨迹线
      visualizationObjects.forEach((object) => {
        if (object.userData?.type === 'robot_pose') {
          // 找到轨迹线并更新
          object.children.forEach(child => {
            if (child.userData?.type === 'trajectory') {
              // 重新创建轨迹几何体
              if (trajectoryPoints.length > 1) {
                child.geometry.dispose()
                child.geometry = new THREE.BufferGeometry().setFromPoints(trajectoryPoints)
              }
            }
          })
        }
      })
    }

    const updateTrajectoryLength = (newLength) => {
      // 限制轨迹点数量
      if (trajectoryPoints.length > newLength) {
        trajectoryPoints.splice(0, trajectoryPoints.length - newLength)
        // 重新创建轨迹线
        updateRobotTrajectory()
      }
    }

    // 导航工具相关方法
    const setFixedFrame = (frameId) => {
      fixedFrameId = frameId || 'map'
      followFrameTracker.reset()
      applyFollowFrame()
      scheduleTransformRefresh()
    }

    const setFollowFrame = (frameId) => {
      followFrameTracker.setFrame(frameId)
      applyFollowFrame()
    }

    const setGoalTopic = (topicName) => {
      goalPublishTopic = typeof topicName === 'string' ? topicName.trim() : ''
    }

    const setNavigationTool = (tool) => {
      const nextTool = tool === 'none' ? 'move' : tool
      const supportedTools = ['move', 'select', '2d_goal', '2d_pose']
      currentNavigationTool = supportedTools.includes(nextTool) ? nextTool : 'move'
      activeTool.value = currentNavigationTool
      debugLog('set navigation tool:', currentNavigationTool)

      clearPreviewArrow()
      isDragging = false
      dragStartPosition = null
      dragCurrentPosition = null

      if (controls) {
        controls.enabled = currentNavigationTool === 'move'
      }

      if (containerRef.value) {
        containerRef.value.focus()

        switch (currentNavigationTool) {
          case 'move':
            activeToolLabel.value = '移动相机 (M)'
            toolHint.value = '左键旋转 · 中键平移 · 滚轮缩放'
            containerRef.value.style.cursor = 'grab'
            break
          case 'select':
            activeToolLabel.value = '选择 (S)'
            toolHint.value = '单击选中对象 · F 聚焦选中对象 · Esc 返回移动相机'
            containerRef.value.style.cursor = 'default'
            break
          case '2d_goal':
            activeToolLabel.value = '2D 目标 (G)'
            toolHint.value = '左键按下选位置，拖动设方向，松开发布 · Esc 取消'
            containerRef.value.style.cursor = 'crosshair'
            break
          case '2d_pose':
            activeToolLabel.value = '2D 位姿估计 (P)'
            toolHint.value = '左键按下选位置，拖动设方向，松开发布 · Esc 取消'
            containerRef.value.style.cursor = 'copy'
            break
          default:
            containerRef.value.style.cursor = 'default'
        }
      }
      emit('tool-change', currentNavigationTool)
    }

    const cancelNavigationSelection = () => {
      clearPreviewArrow()
      isDragging = false
      dragStartPosition = null
      dragCurrentPosition = null
      setNavigationTool('move')
      systemMessage.info('已取消本次目标点')
    }

    const getPreviewArrowLength = (direction) => {
      return Math.max(0.8, Math.min(direction.length(), 3.0))
    }

    const layoutPreviewArrow = (position, direction) => {
      if (!previewArrow) return

      const length = getPreviewArrowLength(direction)
      const shaftLength = Math.max(0.35, length - 0.28)
      const angle = Math.atan2(direction.y, direction.x)
      const shaft = previewArrow.userData.shaft
      const arrowHead = previewArrow.userData.arrowHead

      previewArrow.position.copy(position)
      previewArrow.rotation.z = angle

      if (shaft) {
        shaft.scale.y = shaftLength
        shaft.position.set(shaftLength / 2, 0, 0.04)
      }

      if (arrowHead) {
        arrowHead.position.set(shaftLength + 0.2, 0, 0.04)
      }
    }

    const createPreviewArrow = (position, direction, color = null) => {
      clearPreviewArrow()

      const arrowMaterial = new THREE.MeshBasicMaterial({
        color: color || (currentNavigationTool === '2d_goal' ? 0xff6b35 : 0x4dabf7),
        transparent: true,
        opacity: 0.85,
        depthTest: false
      })

      const shaftGeometry = new THREE.CylinderGeometry(0.035, 0.035, 1, 12)
      const shaft = new THREE.Mesh(shaftGeometry, arrowMaterial)
      shaft.rotation.z = -Math.PI / 2

      const arrowGeometry = new THREE.ConeGeometry(0.14, 0.36, 12)
      const arrowHead = new THREE.Mesh(arrowGeometry, arrowMaterial)
      arrowHead.rotation.z = -Math.PI / 2

      previewArrow = new THREE.Group()
      previewArrow.userData = { shaft, arrowHead }
      previewArrow.add(shaft)
      previewArrow.add(arrowHead)
      scene.add(previewArrow)

      layoutPreviewArrow(position, direction)
    }

    const updatePreviewArrow = (position, direction) => {
      layoutPreviewArrow(position, direction)
    }

    const clearPreviewArrow = () => {
      if (previewArrow) {
        scene.remove(previewArrow)
        previewArrow.children.forEach(child => {
          if (child.geometry) child.geometry.dispose()
          if (child.material) child.material.dispose()
        })
        previewArrow = null
      }
    }

    const handleNavigationToolClick = async (position, orientation) => {
      switch (currentNavigationTool) {
        case '2d_goal':
          await publishGoalPose(position, orientation, goalPublishTopic)
          break
        case '2d_pose':
          await publishPoseEstimate(position, orientation)
          break
      }

      // 发布后重置工具
      setNavigationTool('move')
    }

    const publishGoalPose = async (position, orientation, topicName = '') => {
      debugLog('[Navigation] 开始发布2D目标点')
      debugLog('[Navigation] 连接状态检查:', {
        isConnected: rosbridge.isConnected,
        connectionStatus: connectionStore.connectionStatus,
        websocketState: connectionStore.websocket?.readyState
      })

      if (!rosbridge.isConnected) {
        console.error('[Navigation] ❌ ROS Bridge未连接，无法发布消息')
        systemMessage.error('ROS Bridge未连接，请先连接到ROS系统')
        return false
      }

      const publishTopic = typeof topicName === 'string' ? topicName.trim() : ''
      if (!publishTopic) {
        systemMessage.warning('请先配置期望目标发布话题')
        return false
      }

      // RViz兼容的消息格式 - 2D Goal Pose
      const goalMsg = {
        header: {
          stamp: {
            sec: Math.floor(Date.now() / 1000),
            nanosec: (Date.now() % 1000) * 1000000
          },
          frame_id: fixedFrameId
        },
        pose: {
          position: {
            x: position.x,
            y: position.y,
            z: Number.isFinite(position.z) ? position.z : 0.0
          },
          orientation: {
            x: orientation.x,
            y: orientation.y,
            z: orientation.z,
            w: orientation.w
          }
        }
      }

      debugLog('[Navigation] 发布2D目标点消息:', JSON.stringify(goalMsg, null, 2))

      try {
        const publishResult = await rosbridge.publish(
          publishTopic,
          'geometry_msgs/msg/PoseStamped',
          goalMsg
        )
        // debugLog('[Navigation] rosbridge.publish返回结果:', publishResult)

        if (publishResult) {
          const yawDegrees = (Math.atan2(2 * (orientation.w * orientation.z + orientation.x * orientation.y),
                                         1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z)) * 180 / Math.PI).toFixed(1)
          debugLog(`[Navigation] ✅ 目标点发布成功: (${position.x.toFixed(2)}, ${position.y.toFixed(2)}) 方向: ${yawDegrees}°`)
          systemMessage.success(`已设置目标点: (${position.x.toFixed(2)}, ${position.y.toFixed(2)}) 方向: ${yawDegrees}°`)

          // 额外验证：订阅目标话题来验证消息是否真的发送了
          debugLog('[Navigation] 尝试验证消息发送...')
          return true
        } else {
          throw new Error('发布函数返回false')
        }
      } catch (error) {
        console.error('[Navigation] ❌ 发布目标点失败:', error)
        console.error('[Navigation] 错误堆栈:', error.stack)
        systemMessage.error(`发布目标点失败: ${error.message}`)
        return false
      }
    }

    const normalizeGoalInput = (goal) => ({
      x: Number(goal?.x) || 0,
      y: Number(goal?.y) || 0,
      z: Number(goal?.z) || 0
    })

    const getDefaultGoalOrientation = () => ({
      x: 0,
      y: 0,
      z: 0,
      w: 1
    })

    const previewGoalPoseFromInput = (goal) => {
      if (!scene) return
      const nextGoal = normalizeGoalInput(goal)
      const position = new THREE.Vector3(nextGoal.x, nextGoal.y, nextGoal.z)
      const direction = new THREE.Vector3(1, 0, 0)
      createPreviewArrow(position, direction, 0xff6b35)
    }

    const publishGoalPoseFromInput = (goal, topicName = '') => {
      const nextGoal = normalizeGoalInput(goal)
      const position = new THREE.Vector3(nextGoal.x, nextGoal.y, nextGoal.z)
      previewGoalPoseFromInput(nextGoal)
      return publishGoalPose(position, getDefaultGoalOrientation(), topicName)
    }

    const publishPoseEstimate = async (position, orientation) => {
      debugLog('[Navigation] 开始发布2D位置估计')
      debugLog('[Navigation] 连接状态检查:', {
        isConnected: rosbridge.isConnected,
        connectionStatus: connectionStore.connectionStatus,
        websocketState: connectionStore.websocket?.readyState
      })

      if (!rosbridge.isConnected) {
        console.error('[Navigation] ❌ ROS Bridge未连接，无法发布消息')
        systemMessage.error('ROS Bridge未连接，请先连接到ROS系统')
        return false
      }

      if (!ROS_TOPICS.initialPose) {
        systemMessage.warning('请先配置位置估计发布话题')
        return false
      }

      // RViz兼容的消息格式 - 2D Pose Estimate
      const poseMsg = {
        header: {
          stamp: {
            sec: Math.floor(Date.now() / 1000),
            nanosec: (Date.now() % 1000) * 1000000
          },
          frame_id: fixedFrameId
        },
        pose: {
          pose: {
            position: {
              x: position.x,
              y: position.y,
              z: 0.0  // 2D导航，z固定为0
            },
            orientation: {
              x: orientation.x,
              y: orientation.y,
              z: orientation.z,
              w: orientation.w
            }
          },
          // RViz标准协方差矩阵 (6x6 = 36个元素)
          // 表示位置和姿态的不确定性
          covariance: [
            0.25, 0.0, 0.0, 0.0, 0.0, 0.0,   // x的协方差
            0.0, 0.25, 0.0, 0.0, 0.0, 0.0,   // y的协方差
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    // z的协方差（2D中不使用）
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    // roll的协方差（2D中不使用）
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    // pitch的协方差（2D中不使用）
            0.0, 0.0, 0.0, 0.0, 0.0, 0.06853891909  // yaw的协方差
          ]
        }
      }

      debugLog('[Navigation] 发布2D位置估计消息:', JSON.stringify(poseMsg, null, 2))

      try {
        const publishResult = await rosbridge.publish(
          ROS_TOPICS.initialPose,
          'geometry_msgs/msg/PoseWithCovarianceStamped',
          poseMsg
        )
        // debugLog('[Navigation] rosbridge.publish返回结果:', publishResult)

        if (publishResult) {
          const yawDegrees = (Math.atan2(2 * (orientation.w * orientation.z + orientation.x * orientation.y),
                                         1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z)) * 180 / Math.PI).toFixed(1)
          debugLog(`[Navigation] ✅ 位置估计发布成功: (${position.x.toFixed(2)}, ${position.y.toFixed(2)}) 方向: ${yawDegrees}°`)
          systemMessage.success(`已设置位置估计: (${position.x.toFixed(2)}, ${position.y.toFixed(2)}) 方向: ${yawDegrees}°`)
          return true
        } else {
          throw new Error('发布函数返回false')
        }
      } catch (error) {
        console.error('[Navigation] ❌ 发布位置估计失败:', error)
        systemMessage.error(`发布位置估计失败: ${error.message}`)
      }
    }

    const updateSettings = (settings) => {
      debugLog('更新3D场景设置:', settings)

      // 首先保存设置到持久化存储
      if (settings.type && persistentSettings[settings.type]) {
        Object.assign(persistentSettings[settings.type], settings)
      }

      switch (settings.type) {
        case 'laser':
          // 更新激光雷达设置
          visualizationObjects.forEach((object) => {
            // 2D激光雷达设置
            if (object.userData?.messageType === 'sensor_msgs/msg/LaserScan') {
              // 激光点显示/隐藏
              if (settings.showLaserPoints !== undefined && object.userData?.type === 'laser_points') {
                object.visible = settings.showLaserPoints
              }
              // 激光连线显示/隐藏
              if (settings.showLaserLines !== undefined && object.userData?.type === 'laser_lines') {
                object.visible = settings.showLaserLines
              }
              // 点大小调整
              if (settings.pointSize !== undefined && object.material && object.userData?.type === 'laser_points') {
                object.material.size = settings.pointSize
                object.material.needsUpdate = true
              }
              // 强度显示
              if (settings.showIntensity !== undefined && object.material && object.userData?.type === 'laser_points') {
                // 直接创建新材质以确保vertexColors变化生效
                const oldMaterial = object.material
                const newMaterial = new THREE.PointsMaterial({
                  size: oldMaterial.size,
                  vertexColors: settings.showIntensity,
                  sizeAttenuation: oldMaterial.sizeAttenuation,
                  alphaTest: oldMaterial.alphaTest
                })
                object.material = newMaterial
                oldMaterial.dispose()
              }
            }
            // 3D点云激光设置
            else if (object.userData?.messageType === 'sensor_msgs/msg/PointCloud2') {
              // 激光点显示/隐藏（对3D点云生效）
              if (settings.showLaserPoints !== undefined) {
                object.visible = settings.showLaserPoints
              }
              // 强度显示（对3D点云生效）
              if (settings.showIntensity !== undefined && object.isPoints && object.material) {
                const oldMaterial = object.material
                const newMaterial = createHeightColoredPointsMaterial({
                  size: oldMaterial.size,
                  sizeAttenuation: oldMaterial.sizeAttenuation,
                  opacity: oldMaterial.opacity,
                  transparent: oldMaterial.transparent,
                  depthWrite: oldMaterial.depthWrite
                })
                object.material = newMaterial
                oldMaterial.dispose()
              }
            }
          })
          debugLog('激光雷达设置已更新:', settings)
          break

        case 'pointcloud':
          // 更新点云设置
          visualizationObjects.forEach((object) => {
            if (object.userData?.messageType === 'sensor_msgs/msg/PointCloud2') {
              if (settings.pointSize !== undefined && object.isPoints && object.material) {
                object.material.size = settings.pointSize
                object.material.needsUpdate = true
              }
              if (settings.opacity !== undefined && object.material) {
                object.material.opacity = settings.opacity
                object.material.transparent = settings.opacity < 1.0
                object.material.needsUpdate = true
              }
              if (settings.showIntensity !== undefined && object.isPoints && object.material) {
                const oldMaterial = object.material
                const newMaterial = createHeightColoredPointsMaterial({
                  size: oldMaterial.size,
                  sizeAttenuation: oldMaterial.sizeAttenuation,
                  opacity: oldMaterial.opacity,
                  transparent: oldMaterial.transparent,
                  depthWrite: oldMaterial.depthWrite
                })
                object.material = newMaterial
                oldMaterial.dispose()
              }
            }
          })
          debugLog('点云设置已更新:', settings)
          break
          
        case 'map':
          // 更新地图设置
          if (settings.showMap !== undefined && mapMesh.value) {
            mapMesh.value.visible = settings.showMap
          }
          if (settings.opacity !== undefined && mapMesh.value) {
            mapMesh.value.material.opacity = settings.opacity
            mapMesh.value.material.transparent = settings.opacity < 1.0
            mapMesh.value.material.needsUpdate = true
          }
          if (settings.action === 'reset') {
            // 重置地图视图
            resetCamera()
          }
          if (settings.action === 'center') {
            // 居中显示地图
            if (mapMesh.value) {
              const position = mapMesh.value.position
              camera.position.set(position.x, position.y, position.z + 10)
              camera.lookAt(position)
            }
          }
          debugLog('地图设置已更新:', settings)
          break

        case 'position':
          // 更新位置显示设置
          if (settings.showRobotModel !== undefined) {
            setRobotModelVisible(settings.showRobotModel)
          }
          visualizationObjects.forEach((object) => {
            // 轨迹显示
            if (settings.showTrajectory !== undefined) {
              if (object.userData?.type === 'robot_pose') {
                // 查找轨迹线子对象
                object.children.forEach(child => {
                  if (child.userData?.type === 'trajectory') {
                    child.visible = settings.showTrajectory
                  }
                })
              }
            }
          })
          debugLog('位置设置已更新:', settings)
          if (settings.trajectoryLength !== undefined) {
            // 更新轨迹长度（夹取到10~100）
            const clamped = Math.max(10, Math.min(100, settings.trajectoryLength))
            updateTrajectoryLength(clamped)
          }
          debugLog('位置设置已更新:', settings)
          break

        case 'scene':
          // 更新场景设置
          if (settings.backgroundColor) {
            setBackgroundColor(settings.backgroundColor)
          }
          if (settings.showGrid !== undefined) {
            setGridVisible(settings.showGrid)
          }
          if (settings.showAxes !== undefined) {
            setAxesVisible(settings.showAxes)
          }
          if (settings.viewPreset) {
            setViewPreset(settings.viewPreset)
          }
          if (settings.camera) {
            applyCameraState(settings.camera)
          }
          break
          
        case 'trajectory':
          // 更新轨迹长度设置（从控制面板单独通道传入）
          if (settings.trajectoryLength !== undefined) {
            const clamped = Math.max(10, Math.min(100, settings.trajectoryLength))
            persistentSettings.position.trajectoryLength = clamped
            updateTrajectoryLength(clamped)
            debugLog('更新轨迹长度:', clamped)
          }
          break
      }
    }

    const setViewPreset = (preset) => {
      debugLog('设置视角预设:', preset)

      if (!perspectiveCamera || !orthographicCamera) return
      
      const target = new THREE.Vector3(0, 0, 0)
      
      switch (preset) {
        case 'top':
          // RViz Top-down Orthographic: 正交投影沿 Z 轴俯视 XY 平面
          activateCamera('orthographic')
          camera.up.set(0, 1, 0)
          camera.position.set(0, 0, 20)
          camera.zoom = 1
          camera.updateProjectionMatrix()
          camera.lookAt(target)
          break

        case 'side':
          activateCamera('perspective')
          // 侧视图 - 从Y轴侧面看XZ平面
          camera.up.set(0, 0, 1)
          camera.position.set(0, -20, 5)
          camera.lookAt(target)
          break

        case 'front':
          activateCamera('perspective')
          // 前视图 - 从X轴前方看YZ平面
          camera.up.set(0, 0, 1)
          camera.position.set(20, 0, 5)
          camera.lookAt(target)
          break

        case 'iso':
          activateCamera('perspective')
          // Angled map view with world X horizontal
          camera.up.set(0, 0, 1)
          camera.position.set(0, -14, 10)
          camera.lookAt(target)
          break

        default:
          resetCamera()
      }
      
      if (controls) {
        controls.target.copy(target)
        controls.update()
      }
    }

    const loadMapFile = async (file) => {
      debugLog(`[Scene3D] 加载地图文件: ${file.name}, 大小: ${file.size} bytes`)
      
      try {
        const fileExtension = file.name.toLowerCase().split('.').pop()
        const baseName = file.name.replace(/\.[^/.]+$/, '')
        
        if (fileExtension === 'yaml') {
          const config = await loadMapYaml(file)
          // 存储YAML配置，等待PGM文件
          if (!window.mapConfigs) window.mapConfigs = {}
          window.mapConfigs[baseName] = config
          
          systemMessage.success(`YAML配置已加载: ${file.name}`)
          if (config.image) {
            systemMessage.info(`请选择对应的图像文件: ${config.image}`)
          }
          
        } else if (fileExtension === 'pgm') {
          // 检查是否有对应的YAML配置
          let mapConfig = null
          if (window.mapConfigs && window.mapConfigs[baseName]) {
            mapConfig = window.mapConfigs[baseName]
            debugLog(`[Scene3D] 找到对应的YAML配置:`, mapConfig)
          } else {
            debugLog(`[Scene3D] 未找到${baseName}.yaml配置，使用默认参数`)
            mapConfig = {
              resolution: 0.05,
              origin: [0, 0, 0],
              occupied_thresh: 0.65,
              free_thresh: 0.196,
              negate: false
            }
          }
          
          await loadMapPgmWithConfig(file, mapConfig)
          
        } else {
          systemMessage.error(`不支持的地图文件格式: ${fileExtension}。支持的格式：YAML, PGM`)
          return
        }
        
      } catch (error) {
        console.error(`[Scene3D] 地图文件加载失败:`, error)
        systemMessage.error(`地图文件加载失败: ${error.message}`)
        
        // 提供更详细的错误信息和建议
        if (error.message.includes('PGM文件格式无效')) {
          systemMessage.warning(
            '请确保PGM文件格式正确：支持P5(二进制)和P2(ASCII)格式。请先上传对应的YAML配置文件。',
            { duration: 6000 }
          )
        } else if (error.message.includes('文件读取失败')) {
          systemMessage.warning('文件可能已损坏或不完整，请重新选择文件', { duration: 5000 })
        }
      }
    }

    const loadMapFiles = async (yamlFile, pgmFile) => {
      debugLog(`[Scene3D] 同时加载地图文件: ${yamlFile.name} + ${pgmFile.name}`)

      try {
        // 先加载YAML配置
        const mapConfig = await loadMapYaml(yamlFile)
        debugLog(`[Scene3D] YAML配置加载完成:`, mapConfig)

        // 再用配置加载PGM文件
        await loadMapPgmWithConfig(pgmFile, mapConfig)

        systemMessage.success(`地图加载成功: ${yamlFile.name} + ${pgmFile.name}`)

      } catch (error) {
        console.error(`[Scene3D] 地图文件对加载失败:`, error)
        systemMessage.error(`地图文件对加载失败: ${error.message}`)
      }
    }

    const loadMapYaml = async (file) => {
      debugLog(`[Scene3D] 解析YAML地图配置文件`)
      
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        
        reader.onload = (e) => {
          try {
            const yamlContent = e.target.result
            debugLog('YAML内容:', yamlContent)
            
            // 简单解析YAML内容（手动解析关键字段）
            const mapConfig = parseMapYaml(yamlContent)
            debugLog('解析的地图配置:', mapConfig)
            
            // 如果YAML中指定了图像文件，提示用户也上传PGM文件
            if (mapConfig.image) {
              systemMessage.info(`地图配置已读取，请上传对应的图像文件: ${mapConfig.image}`)
            }
            
            // 存储地图配置用于后续PGM加载
            if (!window.mapConfig) window.mapConfig = {}
            window.mapConfig[file.name] = mapConfig
            
            resolve(mapConfig)
            
          } catch (error) {
            reject(error)
          }
        }
        
        reader.onerror = () => reject(new Error('文件读取失败'))
        reader.readAsText(file)
      })
    }

    const loadMapPgmWithConfig = async (file, mapConfig) => {
      debugLog(`[Scene3D] 加载PGM地图图像，使用配置:`, mapConfig)
      
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        
        reader.onload = (e) => {
          try {
            const arrayBuffer = e.target.result
            const pgmData = parsePgmFile(arrayBuffer)
            
            if (pgmData) {
              createMapFromPgmWithConfig(pgmData, mapConfig, file.name)
              systemMessage.success(`成功加载地图: ${file.name}`)
              resolve(pgmData)
            } else {
              reject(new Error('PGM文件格式无效'))
            }
            
          } catch (error) {
            reject(error)
          }
        }
        
        reader.onerror = () => reject(new Error('文件读取失败'))
        reader.readAsArrayBuffer(file)
      })
    }

    const parseMapYaml = (yamlContent) => {
      const config = {
        resolution: 0.05,
        origin: [0, 0, 0],
        occupied_thresh: 0.65,
        free_thresh: 0.196,
        negate: false,
        image: null
      }
      
      const lines = yamlContent.split('\n')
      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('#') || !trimmed) continue
        
        const parts = trimmed.split(':')
        if (parts.length >= 2) {
          const key = parts[0].trim()
          const value = parts[1].trim()
          
          switch (key) {
            case 'resolution':
              config.resolution = parseFloat(value)
              break
            case 'origin':
              // 解析数组格式 [x, y, theta]
              const originMatch = value.match(/\[(.*?)\]/)
              if (originMatch) {
                config.origin = originMatch[1].split(',').map(v => parseFloat(v.trim()))
              }
              break
            case 'occupied_thresh':
              config.occupied_thresh = parseFloat(value)
              break
            case 'free_thresh':
              config.free_thresh = parseFloat(value)
              break
            case 'negate':
              config.negate = value === 'true' || value === '1'
              break
            case 'image':
              config.image = value.replace(/['"]/g, '')
              break
          }
        }
      }
      
      return config
    }

    const parsePgmFile = (arrayBuffer) => {
      debugLog(`[PGM Parser] 开始解析PGM文件，大小: ${arrayBuffer.byteLength} 字节`)
      
      const uint8Array = new Uint8Array(arrayBuffer)
      let offset = 0
      
      // 读取文本头部，寻找数据开始位置
      let headerLines = []
      let currentLine = ''
      
      // 逐字节读取直到找到完整的头部
      for (let i = 0; i < Math.min(2000, uint8Array.length); i++) {
        const char = String.fromCharCode(uint8Array[i])
        
        if (char === '\n' || char === '\r') {
          if (currentLine.trim()) {
            // 忽略注释行
            if (!currentLine.trim().startsWith('#')) {
              headerLines.push(currentLine.trim())
              debugLog(`[PGM Parser] 头部行 ${headerLines.length}: "${currentLine.trim()}"`)
            }
            currentLine = ''
          }
          
          // 检查是否已经有了完整的头部信息
          if (headerLines.length >= 3) {
            // P5 格式需要: 魔数, 宽度高度, 最大值
            offset = i + 1
            // 跳过可能的额外换行符
            while (offset < uint8Array.length && 
                   (uint8Array[offset] === 10 || uint8Array[offset] === 13)) {
              offset++
            }
            break
          }
        } else {
          currentLine += char
        }
      }
      
      debugLog(`[PGM Parser] 解析到头部行:`, headerLines)
      debugLog(`[PGM Parser] 数据偏移量: ${offset}`)
      
      // 验证头部格式
      if (headerLines.length < 3) {
        console.error('[PGM Parser] 头部信息不完整，至少需要3行')
        return null
      }
      
      // 检查魔数
      const magicNumber = headerLines[0]
      if (magicNumber !== 'P5' && magicNumber !== 'P2') {
        console.error(`[PGM Parser] 不支持的PGM格式: ${magicNumber}，仅支持P5(二进制)和P2(ASCII)`)
        return null
      }
      
      // 解析宽度和高度
      let dimensionLine = headerLines[1]
      let maxValLine = headerLines[2]
      
      // 有些PGM文件可能将宽高分在不同行
      const dimensionParts = dimensionLine.split(/\s+/).filter(p => p)
      let width, height
      
      if (dimensionParts.length >= 2) {
        width = parseInt(dimensionParts[0])
        height = parseInt(dimensionParts[1])
      } else if (dimensionParts.length === 1 && headerLines.length >= 4) {
        // 宽高可能分在两行
        width = parseInt(dimensionParts[0])
        height = parseInt(headerLines[2])
        maxValLine = headerLines[3]
      } else {
        console.error('[PGM Parser] 无法解析图像尺寸')
        return null
      }
      
      const maxVal = parseInt(maxValLine)
      
      if (isNaN(width) || isNaN(height) || isNaN(maxVal)) {
        console.error(`[PGM Parser] 头部参数解析失败: width=${width}, height=${height}, maxVal=${maxVal}`)
        return null
      }
      
      debugLog(`[PGM Parser] ✅ PGM图像信息: ${width}x${height}, 最大值: ${maxVal}, 格式: ${magicNumber}`)
      
      // 读取图像数据
      let imageData
      const expectedDataSize = width * height
      
      if (magicNumber === 'P5') {
        // 二进制格式
        imageData = uint8Array.slice(offset)
        if (imageData.length < expectedDataSize) {
          console.error(`[PGM Parser] 二进制数据不完整: 预期 ${expectedDataSize} 字节, 实际 ${imageData.length} 字节`)
          return null
        }
      } else if (magicNumber === 'P2') {
        // ASCII格式 - 需要解析文本数值
        const remainingData = uint8Array.slice(offset)
        const textData = new TextDecoder('ascii').decode(remainingData)
        const values = textData.trim().split(/\s+/).map(v => parseInt(v)).filter(v => !isNaN(v))
        
        if (values.length < expectedDataSize) {
          console.error(`[PGM Parser] ASCII数据不完整: 预期 ${expectedDataSize} 个值, 实际 ${values.length} 个值`)
          return null
        }
        
        imageData = new Uint8Array(values.slice(0, expectedDataSize))
      }
      
      debugLog(`[PGM Parser] ✅ 成功解析PGM文件: ${width}x${height}, 数据长度: ${imageData.length}`)
      
      return {
        width,
        height,
        maxVal,
        data: imageData,
        format: magicNumber,
        header: headerLines.join('\n')
      }
    }

    const createMapFromPgmWithConfig = (pgmData, mapConfig, filename) => {
      debugLog(`[Scene3D] 创建地图可视化: ${filename}`)
      debugLog(`[Scene3D] 使用地图配置:`, mapConfig)
      
      try {
        // 移除旧地图
        removeVisualization('loaded_map')
        
        const { width, height, data, maxVal } = pgmData
        
        debugLog(`[Scene3D] PGM数据 - 宽度: ${width}, 高度: ${height}, 最大值: ${maxVal}`)
        debugLog(`[Scene3D] 地图配置 - 分辨率: ${mapConfig.resolution}m/pixel, 原点: [${mapConfig.origin.join(', ')}]`)
        
        // 创建Canvas纹理
        const canvas = document.createElement('canvas')
        const ctx = canvas.getContext('2d')
        canvas.width = width
        canvas.height = height
        
        const imageData = ctx.createImageData(width, height)
        const pixels = imageData.data
        
        // 转换PGM数据到RGBA
        for (let i = 0; i < width * height; i++) {
          const pgmValue = data[i]
          const normalizedValue = pgmValue / maxVal
          
          let r, g, b, a
          
          // 根据概率值确定颜色
          if (normalizedValue >= mapConfig.occupied_thresh) {
            // 占用空间 - 黑色
            r = g = b = 0
            a = 255
          } else if (normalizedValue <= mapConfig.free_thresh) {
            // 自由空间 - 白色
            r = g = b = 255
            a = 50  // 半透明
          } else {
            // 未知区域 - 灰色
            r = g = b = 128
            a = 128
          }
          
          // 如果negate为true，反转黑白
          if (mapConfig.negate) {
            if (r === 0 && g === 0 && b === 0) {
              r = g = b = 255
            } else if (r === 255 && g === 255 && b === 255) {
              r = g = b = 0
            }
          }
          
          const pixelIndex = i * 4
          pixels[pixelIndex] = r     // Red
          pixels[pixelIndex + 1] = g // Green
          pixels[pixelIndex + 2] = b // Blue
          pixels[pixelIndex + 3] = a // Alpha
        }
        
        ctx.putImageData(imageData, 0, 0)
        
        // 创建Three.js纹理
        const texture = new THREE.CanvasTexture(canvas)
        texture.flipY = true  // 翻转Y轴以匹配ROS坐标系
        texture.wrapS = THREE.ClampToEdgeWrapping
        texture.wrapT = THREE.ClampToEdgeWrapping
        
        // 创建地图几何体
        const geometry = new THREE.PlaneGeometry(
          width * mapConfig.resolution,
          height * mapConfig.resolution
        )
        
        const material = new THREE.MeshBasicMaterial({
          map: texture,
          transparent: true,
          opacity: 0.8,
          side: THREE.DoubleSide
        })
        
        const mesh = new THREE.Mesh(geometry, material)
        mapMesh.value = mesh  // 存储到reactive变量中
        
        // 计算地图在世界坐标系中的真实尺寸
        const mapWidthMeters = width * mapConfig.resolution
        const mapHeightMeters = height * mapConfig.resolution
        
        debugLog(`[Scene3D] 地图物理尺寸: ${mapWidthMeters.toFixed(2)}m x ${mapHeightMeters.toFixed(2)}m`)
        
        // 地图位置计算 - 正确应用YAML origin偏移
        //
        // ROS地图约定：
        // - origin是地图像素(0,0)对应的世界坐标，即地图左下角在世界坐标系中的位置
        // - 我们需要让地图的几何中心移动到正确位置，使得坐标原点(0,0)在地图中的正确位置
        //
        // Three.js PlaneGeometry的几何中心默认在原点(0,0,0)
        // 地图左下角应该在世界坐标origin，所以地图中心应该在：
        // mapCenter = origin + (mapSize / 2)

        const mapWidthWorld = width * mapConfig.resolution
        const mapHeightWorld = height * mapConfig.resolution

        // 地图几何中心的世界坐标位置
        // ROS坐标系：X向前(北)，Y向左(西)
        // Three.js坐标系：X向右，Y向上
        // 需要正确处理坐标系转换和origin偏移

        // 确保坐标原点(0,0)在地图中正确显示
        // 如果origin=[-10, -5]，表示地图左下角在世界坐标(-10, -5)
        // 地图中心应该在origin + mapSize/2
        const mapX = mapConfig.origin[0] + mapWidthWorld / 2
        const mapY = mapConfig.origin[1] + mapHeightWorld / 2
        const mapZ = mapConfig.origin[2] || 0.0

        // 验证坐标原点在地图中的位置
        // 坐标原点(0,0)相对于地图左下角的偏移
        const originInMapX = 0 - mapConfig.origin[0]  // 原点X - 地图左下角X
        const originInMapY = 0 - mapConfig.origin[1]  // 原点Y - 地图左下角Y

        debugLog(`[Scene3D] 坐标原点(0,0)在地图中的位置检查:`)
        debugLog(`[Scene3D] - 原点相对于地图左下角偏移: (${originInMapX.toFixed(2)}, ${originInMapY.toFixed(2)}) 米`)
        debugLog(`[Scene3D] - 原点在地图中的百分比位置: (${(originInMapX/mapWidthWorld*100).toFixed(1)}%, ${(originInMapY/mapHeightWorld*100).toFixed(1)}%)`)

        // 如果原点不在地图范围内，给出警告
        if (originInMapX < 0 || originInMapX > mapWidthWorld || originInMapY < 0 || originInMapY > mapHeightWorld) {
          console.warn(`[Scene3D] ⚠️ 坐标原点(0,0)在地图范围外！`)
        }

        debugLog(`[Scene3D] 地图世界坐标计算:`)
        debugLog(`[Scene3D] - 地图物理尺寸: ${mapWidthWorld.toFixed(2)}m × ${mapHeightWorld.toFixed(2)}m`)
        debugLog(`[Scene3D] - YAML origin: [${mapConfig.origin.join(', ')}]`)
        debugLog(`[Scene3D] - 计算的地图中心位置: (${mapX.toFixed(3)}, ${mapY.toFixed(3)}, ${mapZ.toFixed(3)})`)

        // 计算坐标原点(0,0)在地图中的相对位置
        const originOffsetX = -mapConfig.origin[0] / mapWidthWorld
        const originOffsetY = -mapConfig.origin[1] / mapHeightWorld
        debugLog(`[Scene3D] - 坐标原点(0,0)在地图中的相对位置: (${(originOffsetX*100).toFixed(1)}%, ${(originOffsetY*100).toFixed(1)}%)`)

        mesh.position.set(mapX, mapY, mapZ)

        // 地图旋转 - 测试不同的旋转方案
        // 问题：地图显示悬浮且与坐标系不匹配
        // Three.js的PlaneGeometry默认在XY平面，法线指向+Z
        // 如果地图悬浮，可能是旋转导致的

        // 方案1：不旋转，直接在XY平面
        mesh.rotation.x = 0
        mesh.rotation.y = 0
        mesh.rotation.z = 0

        debugLog(`[Scene3D] ✅ 地图加载完成:`)
        debugLog(`[Scene3D] - 几何中心位置: (${mapX.toFixed(3)}, ${mapY.toFixed(3)}, ${mapZ.toFixed(3)})`)
        debugLog(`[Scene3D] - 原点配置: [${mapConfig.origin.join(', ')}]`)
        debugLog(`[Scene3D] - 物理尺寸: ${mapWidthMeters.toFixed(2)}m × ${mapHeightMeters.toFixed(2)}m`)
        debugLog(`[Scene3D] - 分辨率: ${mapConfig.resolution}m/pixel`)
        debugLog(`[Scene3D] - 像素尺寸: ${width} × ${height}`)

        // 计算地图在世界坐标系中的实际覆盖范围
        const worldMinX = mapConfig.origin[0]
        const worldMinY = mapConfig.origin[1]
        const worldMaxX = mapConfig.origin[0] + width * mapConfig.resolution
        const worldMaxY = mapConfig.origin[1] + height * mapConfig.resolution
        debugLog(`[Scene3D] - 世界坐标覆盖范围: X=[${worldMinX.toFixed(2)}, ${worldMaxX.toFixed(2)}], Y=[${worldMinY.toFixed(2)}, ${worldMaxY.toFixed(2)}]`)
        
        // 设置用户数据
        mesh.userData = {
          topic: 'loaded_map',
          messageType: 'loaded_map',
          filename: filename,
          config: mapConfig,
          dimensions: { width, height },
          physicalSize: { width: mapWidthMeters, height: mapHeightMeters },
          worldPosition: { x: mapX, y: mapY, z: mapZ }
        }
        
        // 添加到场景
        scene.add(mesh)
        visualizationObjects.set('loaded_map', mesh)
        
        // 自动调整相机以查看地图
        fitCameraToMap(mesh)
        
        debugLog(`[Scene3D] ✅ 地图加载成功:`)
        debugLog(`[Scene3D] - 像素尺寸: ${width}x${height}`)
        debugLog(`[Scene3D] - 物理尺寸: ${mapWidthMeters.toFixed(2)}m x ${mapHeightMeters.toFixed(2)}m`)
        debugLog(`[Scene3D] - 分辨率: ${mapConfig.resolution}m/pixel`)
        debugLog(`[Scene3D] - 世界位置: (${mapX.toFixed(2)}, ${mapY.toFixed(2)}, ${mapZ.toFixed(2)})`)
        debugLog(`[Scene3D] - 原点配置: [${mapConfig.origin.join(', ')}]`)
        
        // 显示成功消息
        systemMessage.success(`地图加载成功！尺寸: ${mapWidthMeters.toFixed(1)}m×${mapHeightMeters.toFixed(1)}m`)
        
      } catch (error) {
        console.error('[Scene3D] 创建地图可视化失败:', error)
        throw error
      }
    }

    const fitCameraToMap = (mapMesh) => {
      if (!camera || !controls || !mapMesh) return
      
      try {
        const box = new THREE.Box3().setFromObject(mapMesh)
        const center = box.getCenter(new THREE.Vector3())
        const size = box.getSize(new THREE.Vector3())
        
        debugLog(`[Scene3D] 地图边界框:`, {
          center: { x: center.x.toFixed(2), y: center.y.toFixed(2), z: center.z.toFixed(2) },
          size: { x: size.x.toFixed(2), y: size.y.toFixed(2), z: size.z.toFixed(2) }
        })
        
        // 对于XY平面上的地图，计算合适的俯视距离
        const maxDim = Math.max(size.x, size.y)
        const distance = maxDim * 1.2  // 适当的观察距离
        
        // 从正上方俯视地图（适合XY平面地图）
        const cameraX = center.x
        const cameraY = center.y
        const cameraZ = Math.max(distance, 10)  // 确保有足够的高度
        
        // 设置相机位置
        camera.position.set(cameraX, cameraY, cameraZ)
        
        // 设置相机目标为地图中心
        const targetPoint = new THREE.Vector3(center.x, center.y, 0.01)  // 地图表面
        camera.lookAt(targetPoint)
        
        if (controls) {
          controls.target.copy(targetPoint)
          controls.update()
        }
        
        debugLog(`[Scene3D] ✅ 相机已适配到地图:`)
        debugLog(`[Scene3D] - 相机位置: (${cameraX.toFixed(2)}, ${cameraY.toFixed(2)}, ${cameraZ.toFixed(2)})`)
        debugLog(`[Scene3D] - 观察目标: (${targetPoint.x.toFixed(2)}, ${targetPoint.y.toFixed(2)}, ${targetPoint.z.toFixed(2)})`)
        debugLog(`[Scene3D] - 观察距离: ${cameraZ.toFixed(2)}m`)
        debugLog(`[Scene3D] - 地图尺寸: ${maxDim.toFixed(2)}m`)
        
      } catch (error) {
        console.error('[Scene3D] 相机适配到地图失败:', error)
      }
    }

    const fitCameraToPointCloud = (pointCloud) => {
      if (!camera || !controls || !pointCloud.geometry) return
      
      try {
        // InstancedMesh 的完整边界框保存在对象上，普通点云保存在几何体上。
        if (pointCloud.isInstancedMesh) {
          pointCloud.computeBoundingBox()
        } else {
          pointCloud.geometry.computeBoundingBox()
        }
        const localBox = pointCloud.isInstancedMesh
          ? pointCloud.boundingBox
          : pointCloud.geometry.boundingBox
        
        if (!localBox) return
        pointCloud.updateMatrixWorld(true)
        const box = localBox.clone().applyMatrix4(pointCloud.matrixWorld)
        
        // 计算点云的中心和大小
        const center = new THREE.Vector3()
        box.getCenter(center)
        
        const size = new THREE.Vector3()
        box.getSize(size)
        const maxDim = Math.max(size.x, size.y, size.z)
        
        // 计算相机距离（确保能看到整个点云）
        const distance = maxDim * 2
        
        // 设置相机位置（从斜上方观察）
        const cameraPosition = new THREE.Vector3(
          center.x + distance * 0.5,
          center.y + distance * 0.5, 
          center.z + distance * 0.7
        )
        
        camera.position.copy(cameraPosition)
        camera.lookAt(center)
        
        if (controls) {
          controls.target.copy(center)
          controls.update()
        }
        
        debugLog(`相机已调整以查看点云 - 中心: (${center.x.toFixed(2)}, ${center.y.toFixed(2)}, ${center.z.toFixed(2)}), 距离: ${distance.toFixed(2)}`)
        
      } catch (error) {
        console.error('调整相机视角失败:', error)
      }
    }

    const addDebugInfo = () => {
      if (!scene) return
      
      // 收集详细的调试信息
      const debugInfo = {
        timestamp: new Date().toISOString(),
        scene: {
          objects: visualizationObjects.size,
          subscriptions: rosSubscriptions.size,
          sceneChildren: scene.children.length,
          camera: camera ? {
            position: {
              x: camera.position.x.toFixed(2),
              y: camera.position.y.toFixed(2),
              z: camera.position.z.toFixed(2)
            },
            target: controls ? {
              x: controls.target.x.toFixed(2),
              y: controls.target.y.toFixed(2),
              z: controls.target.z.toFixed(2)
            } : null
          } : null
        },
        rosbridge: {
          connected: rosbridge?.isConnected ?? false,
          subscriptionCount: rosSubscriptions.size
        },
        performance: {
          fps: performanceStats.value.fps,
          objects: performanceStats.value.objects,
          vertices: performanceStats.value.vertices
        }
      }
      
      debugLog('=== 🔍 3D场景详细调试信息 ===')
      debugLog('时间戳:', debugInfo.timestamp)
      debugLog('--- 场景状态 ---')
      debugLog('可视化对象数量:', debugInfo.scene.objects)
      debugLog('ROS订阅数量:', debugInfo.scene.subscriptions)
      debugLog('Three.js场景子对象数量:', debugInfo.scene.sceneChildren)
      debugLog('--- 相机信息 ---')
      debugLog('相机位置:', debugInfo.scene.camera?.position)
      debugLog('相机目标:', debugInfo.scene.camera?.target)
      debugLog('--- ROS连接 ---')
      debugLog('ROSBridge连接状态:', debugInfo.rosbridge.connected)
      debugLog('--- 性能统计 ---')
      debugLog('FPS:', debugInfo.performance.fps)
      debugLog('渲染对象数:', debugInfo.performance.objects)
      debugLog('顶点数:', debugInfo.performance.vertices)

      debugLog('--- 可视化对象详情 ---')
      if (visualizationObjects.size === 0) {
        debugLog('⚠️ 没有可视化对象')
      } else {
        visualizationObjects.forEach((obj, topic) => {
          debugLog(`📊 ${topic}:`, {
            类型: obj.userData?.messageType,
            点数: obj.userData?.pointCount,
            可见: obj.visible,
            位置: `(${obj.position.x.toFixed(2)}, ${obj.position.y.toFixed(2)}, ${obj.position.z.toFixed(2)})`,
            缩放: `(${obj.scale.x.toFixed(2)}, ${obj.scale.y.toFixed(2)}, ${obj.scale.z.toFixed(2)})`,
            用户数据: obj.userData
          })
        })
      }
      
      debugLog('--- ROS订阅详情 ---')
      if (rosSubscriptions.size === 0) {
        debugLog('⚠️ 没有ROS订阅')
      } else {
        rosSubscriptions.forEach((subscription, topic) => {
          debugLog(`📡 ${topic}:`, {
            订阅对象: subscription,
            订阅时间: subscription?.timestamp ? new Date(subscription.timestamp).toLocaleString() : '未知'
          })
        })
      }
      
      debugLog('--- Three.js场景对象 ---')
      scene.children.forEach((child, index) => {
        debugLog(`🎭 场景对象 ${index}:`, {
          类型: child.type,
          名称: child.name || '未命名',
          可见: child.visible,
          位置: `(${child.position.x.toFixed(2)}, ${child.position.y.toFixed(2)}, ${child.position.z.toFixed(2)})`,
          用户数据: child.userData
        })
      })
      
      debugLog('=== 🔍 调试信息结束 ===')
      
      // 显示简化的用户消息
      systemMessage.info(`调试信息已输出到控制台 - 对象:${debugInfo.scene.objects} 订阅:${debugInfo.scene.subscriptions} FPS:${debugInfo.performance.fps}`)
      
      return debugInfo
    }

    const checkSubscriptionStatus = () => {
      debugLog('=== 🔍 ROS订阅状态检查 ===')
      
      const now = Date.now()
      let activeSubscriptions = 0
      let inactiveSubscriptions = 0
      let totalMessages = 0
      
      if (rosSubscriptions.size === 0) {
        debugLog('⚠️ 没有任何ROS订阅')
        systemMessage.warning('没有任何ROS订阅')
        return
      }
      
      rosSubscriptions.forEach((subscription, topic) => {
        const timeSinceSubscribe = now - (subscription.subscribeTime || 0)
        const timeSinceLastMessage = subscription.lastMessageTime > 0 ? now - subscription.lastMessageTime : -1
        const messageCount = subscription.messageCount || 0
        
        debugLog(`📡 ${topic}:`)
        debugLog(`  - 订阅时长: ${(timeSinceSubscribe / 1000).toFixed(1)}秒`)
        debugLog(`  - 消息数量: ${messageCount}`)
        debugLog(`  - 最后消息: ${timeSinceLastMessage > 0 ? (timeSinceLastMessage / 1000).toFixed(1) + '秒前' : '从未收到'}`)
        
        if (messageCount > 0) {
          const avgFreq = messageCount / (timeSinceSubscribe / 1000)
          debugLog(`  - 平均频率: ${avgFreq.toFixed(2)} Hz`)
          activeSubscriptions++
        } else {
          debugLog(`  - ⚠️ 此主题没有收到任何数据`)
          inactiveSubscriptions++
        }
        
        totalMessages += messageCount
      })
      
      debugLog('=== 📊 订阅统计 ===')
      debugLog(`总订阅数: ${rosSubscriptions.size}`)
      debugLog(`活跃订阅: ${activeSubscriptions}`)
      debugLog(`无数据订阅: ${inactiveSubscriptions}`)
      debugLog(`总消息数: ${totalMessages}`)
      
      // 用户反馈
      if (inactiveSubscriptions > 0) {
        systemMessage.warning(`有 ${inactiveSubscriptions} 个主题没有数据，请检查ROS系统是否正在发布这些主题`)
      } else if (activeSubscriptions > 0) {
        systemMessage.success(`所有 ${activeSubscriptions} 个订阅都在正常接收数据`)
      }
    }
    
    return {
      containerRef,
      loading,
      activeTool,
      activeToolLabel,
      toolHint,
      mapMesh,
      mapTexture,
      onMouseDown,
      onMouseMove,
      onMouseUp,
      handleResize: onWindowResize,
      // 暴露给父组件的方法
      resetCamera,
      setGridVisible,
      setAxesVisible,
      getCameraState,
      applyCameraState,
      captureScreenshot,
      startRecording,
      stopRecording,
      setBackgroundColor,
      updateRenderSettings,
      // ROS集成方法
      subscribeToRosTopic,
      subscribeToDefaultVisualizationTopics,
      unsubscribeFromRosTopic,
      updateVisualization,
      removeVisualization,
      setVisualizationVisible,
      configureDisplay,
      getPerformanceStats,
      updateSettings,
      setViewPreset,
      setNavigationTool,
      setGoalTopic,
      setPositionOdomTopic,
      setRobotModelVisible,
      focusSelection,
      previewGoalPoseFromInput,
      publishGoalPoseFromInput,
      setFixedFrame,
      setFollowFrame,
      loadMapFile,
      loadMapFiles,
      fitCameraToPointCloud,
      fitCameraToMap,
      addDebugInfo,
      checkSubscriptionStatus,
      // 位置信息处理
      updateOdometry,
      updatePoseStamped,
      updatePoseWithCovarianceStamped,
      // 清理方法
      clearAllVisualizations,
      unsubscribeAllTopics
    }
  }
}
</script>

<style scoped>
.scene3d-container {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  background: transparent;
  outline: none;
}

.scene3d-container:focus {
  box-shadow: inset 0 0 0 2px var(--accent-strong-50);
}

.loading-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 15px;
  color: var(--text-primary);
  font-size: 14px;
  z-index: 1000;
}

.loading-spinner {
  display: flex;
  justify-content: center;
  align-items: center;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--text-inverse-faint);
  border-top: 3px solid var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.tool-hint {
  position: absolute;
  bottom: 10px;
  right: 10px;
  z-index: 100;
  opacity: 0.7;
  transition: opacity 0.3s;
}

.tool-hint:hover {
  opacity: 1;
}

.hint-content {
  background: var(--surface-tooltip);
  backdrop-filter: blur(5px);
  color: var(--text-inverse-muted);
  padding: 6px 10px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  border: 1px solid var(--accent-strong-30);
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint-content strong {
  color: var(--accent-glow);
  font-size: 11px;
  white-space: nowrap;
}
</style>
