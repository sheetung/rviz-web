<template>
  <div class="status-panel" :class="{ 'status-panel--wide': wide }">
    <div class="status-grid">
      <!-- 连接状态 -->
      <div class="status-item connection" :class="connectionStatusClass">
        <div class="status-icon">
          <el-icon size="20" :color="connectionColor">
            <Link />
          </el-icon>
        </div>
        <div class="status-content">
          <div class="status-label">连接</div>
          <div class="status-value">{{ connectionData.status }}</div>
          <div class="status-extra">延迟 {{ formatLatency(connectionStore.connectionLatency) }}</div>
        </div>
      </div>
      
      <!-- 运行状态 -->
      <div class="status-item system" :class="systemStatusClass">
        <div class="status-icon">
          <el-icon size="20" :color="systemColor">
            <Setting />
          </el-icon>
        </div>
        <div class="status-content">
          <div class="status-label">系统</div>
          <div class="status-value">CPU {{ formatPercent(systemData.cpuUsage) }}</div>
          <div class="status-extra">
            内存 {{ formatPercent(systemData.memUsage) }} · 温度 {{ formatTemperature(systemData.temperature) }}
          </div>
        </div>
      </div>

      <!-- 配置状态 -->
      <div class="status-item config" :class="configStatusClass">
        <div class="status-icon">
          <el-icon size="20" :color="configColor">
            <Document />
          </el-icon>
        </div>
        <div class="status-content">
          <div class="status-label">配置</div>
          <div class="status-value status-value--ellipsis" :title="configStatusStore.currentConfigName || '未加载配置'">
            {{ configStatusStore.currentConfigName || '未加载配置' }}
          </div>
          <div class="status-extra">
            <template v-if="configStatusStore.currentConfigName">
              {{ configStatusStore.isDirty ? '有未保存修改' : '已保存' }} · 最近保存 {{ formatSavedTime(configStatusStore.lastSavedAt) }}
            </template>
            <template v-else>等待读取 .rvizweb</template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Document, Setting, Link } from '@element-plus/icons-vue'
import { useConfigStatusStore } from '../../composables/useConfigStatusStore'
import { useConnectionStore } from '../../composables/useConnectionStore'

export default {
  name: 'StatusPanel',
  components: {
    Document,
    Setting,
    Link
  },

  props: {

    compact: {

      type: Boolean,

      default: false

    },

    wide: {

      type: Boolean,

      default: false

    }

  },

  setup() {
    const configStatusStore = useConfigStatusStore()
    const connectionStore = useConnectionStore()
    
    // 状态数据
    const connectionData = computed(() => ({
      status: connectionStore.isConnected ? '已连接' : '未连接',
      quality: connectionStore.isConnected ? 'GOOD' : 'DISCONNECTED'
    }))
    
    const systemData = ref({
      cpuUsage: null,
      memUsage: null,
      temperature: null
    })
    
    // 连接相关计算属性
    const connectionStatusClass = computed(() => {
      switch (connectionData.value.quality) {
        case 'GOOD': return 'status-good'
        case 'POOR': return 'status-warning'
        case 'DISCONNECTED': return 'status-critical'
        default: return 'status-inactive'
      }
    })
    
    const connectionColor = computed(() => {
      switch (connectionData.value.quality) {
        case 'GOOD': return 'var(--success)'
        case 'POOR': return 'var(--warning)'
        case 'DISCONNECTED': return 'var(--danger)'
        default: return 'var(--text-muted)'
      }
    })
    
    // 系统相关计算属性
    const systemStatusClass = computed(() => {
      const cpu = systemData.value.cpuUsage
      const mem = systemData.value.memUsage
      const temp = systemData.value.temperature

      if (cpu === null && mem === null && temp === null) return 'status-inactive'
      
      if (cpu > 80 || mem > 80 || temp > 60) return 'status-critical'
      if (cpu > 60 || mem > 60 || temp > 50) return 'status-warning'
      return 'status-good'
    })
    
    const systemColor = computed(() => {
      const cpu = systemData.value.cpuUsage
      const mem = systemData.value.memUsage
      const temp = systemData.value.temperature

      if (cpu === null && mem === null && temp === null) return 'var(--text-muted)'
      
      if (cpu > 80 || mem > 80 || temp > 60) return 'var(--danger)'
      if (cpu > 60 || mem > 60 || temp > 50) return 'var(--warning)'
      return 'var(--success)'
    })

    const configStatusClass = computed(() => {
      if (!configStatusStore.currentConfigName) return 'status-inactive'
      return configStatusStore.isDirty ? 'status-warning' : 'status-good'
    })

    const configColor = computed(() => {
      if (!configStatusStore.currentConfigName) return 'var(--text-muted)'
      return configStatusStore.isDirty ? 'var(--warning)' : 'var(--success)'
    })
    
    let systemStatusTimer = null

    const toNumber = (value, fallback = 0) => {
      const number = Number(value)
      return Number.isFinite(number) ? number : fallback
    }

    const updateSystemMetrics = (statusData = {}) => {
      if (statusData.cpu_usage !== undefined) {
        systemData.value.cpuUsage = statusData.cpu_usage === null ? null : toNumber(statusData.cpu_usage, null)
      }
      if (statusData.memory_usage !== undefined) {
        systemData.value.memUsage = statusData.memory_usage === null ? null : toNumber(statusData.memory_usage, null)
      }
      if (statusData.mem_usage !== undefined) {
        systemData.value.memUsage = toNumber(statusData.mem_usage)
      }
      if (statusData.cpu_temperature !== undefined) {
        systemData.value.temperature = statusData.cpu_temperature === null
          ? null
          : toNumber(statusData.cpu_temperature, null)
      }
      if (statusData.temperature !== undefined) {
        systemData.value.temperature = statusData.temperature === null
          ? null
          : toNumber(statusData.temperature, null)
      }
    }

    const fetchSystemStatus = async () => {
      if (!connectionStore.isConnected) {
        systemData.value = {
          cpuUsage: null,
          memUsage: null,
          temperature: null
        }
        return
      }

      try {
        const statusData = await connectionStore.getSystemStatus()
        if (statusData) updateSystemMetrics(statusData)
      } catch (error) {
        console.warn('Failed to fetch system status:', error)
      }
    }
    
    const formatPercent = (value) => {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return '--'
      }
      return `${Math.round(toNumber(value))}%`
    }

    const formatLatency = (value) => {
      return value === null || value === undefined ? '--' : `${value}ms`
    }

    const formatTemperature = (value) => {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return '--'
      }
      return `${Number(value).toFixed(1)}°C`
    }

    const formatSavedTime = (value) => {
      if (!value) return '--'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return '--'

      const pad = (number) => String(number).padStart(2, '0')
      return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    }
    
    onMounted(() => {
      fetchSystemStatus()
      systemStatusTimer = setInterval(fetchSystemStatus, 3000)
    })
    
    onUnmounted(() => {
      if (systemStatusTimer) {
        clearInterval(systemStatusTimer)
      }
    })
    
    return {
      connectionData,
      configStatusStore,
      connectionStore,
      systemData,
      connectionStatusClass,
      connectionColor,
      systemStatusClass,
      systemColor,
      configStatusClass,
      configColor,
      formatPercent,
      formatLatency,
      formatTemperature,
      formatSavedTime
    }
  }
}
</script>

<style scoped>
.status-panel {
  padding: 8px;
  font-size: 12px;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  flex: 1;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-subtle);
  backdrop-filter: blur(10px);
  transition: all 0.3s ease;
}

.status-item.status-good {
  border-color: var(--success);
  background: var(--success-soft);
}

.status-item.status-warning {
  border-color: var(--warning);
  background: var(--warning-soft);
}

.status-item.status-critical {
  border-color: var(--danger);
  background: var(--danger-surface);
}

.status-item.status-inactive {
  border-color: var(--text-muted);
  background: var(--muted-surface);
  opacity: 0.7;
}

.status-icon {
  flex-shrink: 0;
}

.status-content {
  flex: 1;
  min-width: 0;
}

.status-label {
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.status-value {
  font-weight: bold;
  color: var(--text-primary);
  font-size: 13px;
}

.status-value--ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-extra {
  color: var(--text-secondary);
  font-size: 10px;
  margin-top: 1px;
}

.status-panel--wide {
  padding: 0;
  height: auto;
  display: block;
  align-items: center;
}

.status-panel--wide .status-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  flex: none;
  min-width: 0;
}

.status-panel--wide .status-item {
  min-width: 0;
  padding: 7px 10px;
}

.status-panel--wide .status-icon {
  display: flex;
}

.status-panel--wide .status-label {
  color: var(--text-secondary);
}

.status-panel--wide .status-value {
  font-weight: 700;
  line-height: 1.2;
}

@media (max-width: 1100px) {
  .status-panel--wide .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .status-panel--wide .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
