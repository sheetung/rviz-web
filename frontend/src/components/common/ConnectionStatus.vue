<template>
  <div ref="statusRef" class="connection-status">
    <el-badge
      :type="badgeType"
      is-dot
      class="connection-badge"
    >
      <el-button
        :type="buttonType"
        size="small"
        @click="toggleDetails"
        :loading="connectionStore.isConnecting"
      >
        <el-icon><Connection /></el-icon>
        {{ connectionStore.connectionStatusText }}
        <el-icon class="details-arrow" :class="{ open: showDetails }"><ArrowDown /></el-icon>
      </el-button>
    </el-badge>

    <transition name="status-popover">
      <div v-if="showDetails" class="status-popover-panel">
        <div class="status-popover-header">
          <div>
            <div class="status-title">系统状态</div>
            <div class="status-subtitle">{{ connectionStore.wsUrl }}</div>
          </div>
          <el-button size="small" text @click.stop="reconnect">重连</el-button>
        </div>

        <StatusPanel :compact="true" wide />

        <div class="connection-meta">
          <span>订阅 {{ connectionStore.subscribedTopics.length }} 个主题</span>
          <span>重连 {{ connectionStore.reconnectAttempts || 0 }} 次</span>
        </div>

        <div class="version-meta" aria-label="版本信息">
          <span>前端 v{{ frontendVersion }}</span>
          <span>后端 v{{ backendVersion }}</span>
        </div>

        <div v-if="connectionStore.subscribedTopics.length > 0" class="subscribed-topics">
          <el-tag
            v-for="topic in visibleTopics"
            :key="topic"
            size="small"
            class="topic-tag"
          >
            {{ topic }}
          </el-tag>
          <span v-if="hiddenTopicCount > 0" class="topic-more">+{{ hiddenTopicCount }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Connection, ArrowDown } from '@element-plus/icons-vue'
import { useConnectionStore } from '../../composables/useConnectionStore'
import { appApi } from '../../services/api'
import StatusPanel from '../panels/StatusPanel.vue'

export default {
  name: 'ConnectionStatus',
  components: {
    Connection,
    ArrowDown,
    StatusPanel
  },
  setup() {
    const connectionStore = useConnectionStore()
    const showDetails = ref(false)
    const statusRef = ref(null)
    const frontendVersion = import.meta.env.VITE_FRONTEND_VERSION || 'unknown'
    const backendVersion = ref('unknown')

    // 徽章类型
    const badgeType = computed(() => {
      switch (connectionStore.connectionStatus) {
        case 'connected':
          return 'success'
        case 'connecting':
          return 'warning'
        case 'error':
          return 'danger'
        default:
          return 'info'
      }
    })

    // 按钮类型
    const buttonType = computed(() => {
      switch (connectionStore.connectionStatus) {
        case 'connected':
          return 'success'
        case 'connecting':
          return 'warning'
        case 'error':
          return 'danger'
        default:
          return 'default'
      }
    })

    const visibleTopics = computed(() => connectionStore.subscribedTopics.slice(0, 8))
    const hiddenTopicCount = computed(() => Math.max(0, connectionStore.subscribedTopics.length - visibleTopics.value.length))

    const toggleDetails = () => {
      showDetails.value = !showDetails.value
    }

    const closeDetails = () => {
      showDetails.value = false
    }

    const handleDocumentClick = (event) => {
      if (!showDetails.value || statusRef.value?.contains(event.target)) return
      closeDetails()
    }

    const reconnect = () => {
      connectionStore.disconnect()
      connectionStore.connect()
    }

    const fetchBackendVersion = async () => {
      try {
        const response = await appApi.getVersion()
        backendVersion.value = response?.version || 'unknown'
      } catch {
        backendVersion.value = 'unavailable'
      }
    }

    onMounted(() => {
      document.addEventListener('click', handleDocumentClick)
      fetchBackendVersion()
    })

    onUnmounted(() => {
      document.removeEventListener('click', handleDocumentClick)
    })

    return {
      statusRef,
      connectionStore,
      showDetails,
      badgeType,
      buttonType,
      visibleTopics,
      hiddenTopicCount,
      frontendVersion,
      backendVersion,
      toggleDetails,
      closeDetails,
      reconnect
    }
  }
}
</script>

<style scoped>
.connection-status {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
}

.connection-badge {
  margin-right: 10px;
}

.details-arrow {
  margin-left: 4px;
  transition: transform 0.2s ease;
}

.details-arrow.open {
  transform: rotate(180deg);
}

.status-popover-panel {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: min(760px, calc(100vw - 28px));
  padding: 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 16px 40px var(--shadow-color-35);
  z-index: 3000;
}

.status-popover-panel::before {
  content: '';
  position: absolute;
  top: -6px;
  right: 28px;
  width: 10px;
  height: 10px;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
  border-top: 1px solid var(--border);
  transform: rotate(45deg);
}

.status-popover-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.status-title {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
}

.status-subtitle {
  max-width: 560px;
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.connection-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 11px;
}

.version-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 8px;
  padding-top: 8px;
  color: var(--text-muted);
  font-size: 11px;
  border-top: 1px solid var(--border);
}

.subscribed-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.topic-tag {
  max-width: 180px;
  margin: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topic-more {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 24px;
}

.status-popover-enter-active,
.status-popover-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.status-popover-enter-from,
.status-popover-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 780px) {
  .status-popover-panel {
    right: -8px;
  }
}
@media (pointer: coarse) {
  .status-popover-panel { max-height: calc(100dvh - var(--header-h) - 32px - env(safe-area-inset-top) - env(safe-area-inset-bottom)); overflow-y: auto; overscroll-behavior: contain; }
}
</style>
