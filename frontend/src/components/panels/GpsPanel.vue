<template>
  <div class="position-panel">
    <div
      class="position-source"
      :class="positionStatusClass"
      :title="positionStatusText"
      :aria-label="positionStatusText"
    >
      <span class="status-dot" aria-hidden="true"></span>
      <span>{{ currentOdomTopic || '未选择 Odom 话题' }}</span>
    </div>

    <div class="position-info compact">
      <div class="position-labels">
        <span>X</span>
        <span>Y</span>
        <span>Z</span>
      </div>
      <div class="position-values">
        <span>{{ positionData.x.toFixed(3) }}</span>
        <span>{{ positionData.y.toFixed(3) }}</span>
        <span>{{ positionData.z.toFixed(3) }}</span>
      </div>
      <div class="position-labels">
        <span>ROLL</span>
        <span>PITCH</span>
        <span>YAW</span>
      </div>
      <div class="position-values">
        <span>{{ positionData.roll.toFixed(2) }}</span>
        <span>{{ positionData.pitch.toFixed(2) }}</span>
        <span>{{ positionData.yaw.toFixed(2) }}</span>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, computed, onUnmounted, watch } from 'vue'
import { useRosbridge } from '../../composables/useRosbridge'
import { useConnectionStore } from '../../composables/useConnectionStore'

export default {
  name: 'PosePanel',
  props: {
    currentOdomTopic: {
      type: String,
      default: ''
    }
  },
  setup(props) {
    const rosbridge = useRosbridge()
    const connectionStore = useConnectionStore()

    const positionData = ref({
      x: 0.0,
      y: 0.0,
      z: 0.0,
      roll: 0.0,
      pitch: 0.0,
      yaw: 0.0,
      status: 'INACTIVE', // ACTIVE, INACTIVE, NO_DATA
      lastUpdate: null,
      sourceTopic: ''
    })

    const positionStatusClass = computed(() => {
      switch (positionData.value.status) {
        case 'ACTIVE':
          return 'status-active'
        case 'INACTIVE':
          return 'status-inactive'
        case 'NO_DATA':
          return 'status-no-fix'
        default:
          return 'status-inactive'
      }
    })

    const positionStatusText = computed(() => {
      switch (positionData.value.status) {
        case 'ACTIVE':
          return positionData.value.sourceTopic || '位置活跃'
        case 'INACTIVE':
          return '位置不活跃'
        case 'NO_DATA':
          return '无位置数据'
        default:
          return '位置未知状态'
      }
    })

    const subscriptions = []

    const toNumber = (value, fallback = 0) => {
      const number = Number(value)
      return Number.isFinite(number) ? number : fallback
    }

    const extractPose = (message, type) => {
      if (type === 'nav_msgs/msg/Odometry') {
        const pose = message.pose
        const poseData = pose?.pose
        return {
          position: poseData?.position,
          orientation: poseData?.orientation
        }
      }

      if (type === 'geometry_msgs/msg/PoseStamped') {
        const pose = message.pose
        return {
          position: pose?.position,
          orientation: pose?.orientation
        }
      }

      return { position: null, orientation: null }
    }

    const updatePositionFromMessage = (topic, type, message) => {
      const { position, orientation } = extractPose(message, type)

      if (!position) {
        console.warn('[PosePanel] Failed to parse pose from ' + topic, message)
        return
      }

      positionData.value.x = toNumber(position.x)
      positionData.value.y = toNumber(position.y)
      positionData.value.z = toNumber(position.z)
      positionData.value.status = 'ACTIVE'
      positionData.value.lastUpdate = new Date()
      positionData.value.sourceTopic = topic

      if (orientation) {
        const qx = toNumber(orientation.x)
        const qy = toNumber(orientation.y)
        const qz = toNumber(orientation.z)
        const qw = toNumber(orientation.w, 1)

        const sinr_cosp = 2 * (qw * qx + qy * qz)
        const cosr_cosp = 1 - 2 * (qx * qx + qy * qy)
        const roll = Math.atan2(sinr_cosp, cosr_cosp)

        const sinp = 2 * (qw * qy - qz * qx)
        const pitch = Math.abs(sinp) >= 1 ? (Math.sign(sinp) * Math.PI / 2) : Math.asin(sinp)

        const siny_cosp = 2 * (qw * qz + qx * qy)
        const cosy_cosp = 1 - 2 * (qy * qy + qz * qz)
        const yaw = Math.atan2(siny_cosp, cosy_cosp)

        positionData.value.roll = roll * 180 / Math.PI
        positionData.value.pitch = pitch * 180 / Math.PI
        positionData.value.yaw = yaw * 180 / Math.PI
      } else {
        positionData.value.roll = 0.0
        positionData.value.pitch = 0.0
        positionData.value.yaw = 0.0
      }

      if (!updatePositionFromMessage._lastLogTime || Date.now() - updatePositionFromMessage._lastLogTime > 5000) {
        console.log('[PosePanel] ' + topic + ' position: (' + positionData.value.x.toFixed(3) + ', ' + positionData.value.y.toFixed(3) + ', ' + positionData.value.z.toFixed(3) + ')')
        updatePositionFromMessage._lastLogTime = Date.now()
      }
    }

    const clearPositionSubscriptions = () => {
      subscriptions.forEach(({ topic, subscription }) => {
        try {
          rosbridge.unsubscribe(subscription || topic)
          console.log('[PosePanel] unsubscribed: ' + topic)
        } catch (e) {
          console.warn('[PosePanel] failed to unsubscribe ' + topic + ':', e)
        }
      })
      subscriptions.length = 0
    }

    const subscribeToPosition = () => {
      if (!connectionStore.isConnected) {
        positionData.value.status = 'INACTIVE'
        return
      }

      const topic = props.currentOdomTopic || ''
      if (!topic) {
        positionData.value.status = 'NO_DATA'
        positionData.value.sourceTopic = ''
        return
      }

      if (subscriptions.length > 0) {
        return
      }

      console.log('[PosePanel] 订阅无人机 odom 位姿信息: ' + topic)

      try {
        const type = 'nav_msgs/msg/Odometry'
        const subscription = rosbridge.subscribe(topic, type, (message) => {
          updatePositionFromMessage(topic, type, message)
        })

        if (subscription) {
          subscriptions.push({ topic, subscription })
          console.log('[PosePanel] subscribed: ' + topic)
        }
      } catch (error) {
        console.warn('[PosePanel] failed to subscribe ' + topic + ':', error)
      }

      if (subscriptions.length === 0) {
        positionData.value.status = 'NO_DATA'
      }
    }

    const stopConnectionWatch = watch(
      () => connectionStore.isConnected,
      (isConnected) => {
        if (isConnected) {
          subscribeToPosition()
        } else {
          clearPositionSubscriptions()
          positionData.value.status = 'INACTIVE'
          positionData.value.sourceTopic = ''
        }
      },
      { immediate: true }
    )

    const stopTopicWatch = watch(
      () => props.currentOdomTopic,
      (topic) => {
        clearPositionSubscriptions()
        positionData.value.status = topic ? 'NO_DATA' : 'INACTIVE'
        positionData.value.sourceTopic = ''
        subscribeToPosition()
      }
    )

    onUnmounted(() => {
      console.log('[PosePanel] 组件卸载 - 清理所有订阅')
      stopConnectionWatch()
      stopTopicWatch()
      clearPositionSubscriptions()
    })

    return {
      positionData,
      positionStatusClass,
      positionStatusText
    }
  }
}
</script>

<style scoped>
.position-panel {
  padding: 8px 12px;
  font-size: 12px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.position-info {
  flex: 1;
  display: grid;
  gap: 2px;
}

.position-labels,
.position-values {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-items: center;
}

.position-labels {
  color: var(--text-secondary);
  font-size: 11px;
  letter-spacing: 0.04em;
}

.position-values {
  color: var(--text-primary);
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  font-weight: 600;
}

.position-item,
.info-item,
.info-item.compact-item {
  display: none;
}

.position-source {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
}

.position-source span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-row {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 8px;
  align-items: center;
  margin-bottom: 3px;
}

.label {
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 11px;
  text-align: right;
}

.value {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
}

.accuracy-good {
  color: var(--success);
}

.accuracy-medium {
  color: var(--warning);
}

.accuracy-poor {
  color: var(--danger);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-active .status-dot {
  background: var(--success);
  box-shadow: 0 0 6px var(--success-glow);
}

.status-inactive .status-dot {
  background: var(--text-muted);
}

.status-no-fix .status-dot {
  background: var(--danger);
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0.3; }
}
</style>
