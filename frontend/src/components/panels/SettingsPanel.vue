<template>
  <div class="settings-panel">
    <section class="settings-section">
      <div class="section-heading">
        <h4>配置文件</h4>
        <span>.rvizweb</span>
      </div>

      <div class="field-row">
        <label>保存为</label>
        <div class="inline-actions">
          <el-input v-model="configName" placeholder="default.rvizweb" size="small" />
          <el-button size="small" type="primary" @click="saveConfig">保存</el-button>
        </div>
      </div>

      <div class="field-row">
        <label>读取配置</label>
        <div class="inline-actions">
          <el-select v-model="selectedConfigName" placeholder="选择配置" size="small" class="config-select">
            <el-option v-for="file in configFiles" :key="file" :label="file" :value="file" />
          </el-select>
          <el-button size="small" @click="loadSelectedConfig">读取</el-button>
          <el-button size="small" type="danger" text @click="deleteSelectedConfig">删除</el-button>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <div class="section-heading">
        <h4>外观</h4>
        <span>随配置保存</span>
      </div>
      <div class="field-row">
        <label>主题</label>
        <el-select v-model="selectedTheme" size="small">
          <el-option label="深色" value="dark" />
          <el-option label="浅色" value="light" />
        </el-select>
      </div>
    </section>

    <section class="settings-section">
      <div class="section-heading">
        <h4>当前配置</h4>
        <span>预览</span>
      </div>
      <div class="summary-grid">
        <div class="summary-item">
          <span class="summary-label">Fixed Frame</span>
          <span class="summary-value">{{ configSummary.fixedFrame }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Odom</span>
          <span class="summary-value">{{ configSummary.odomTopic || '-' }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">PointCloud</span>
          <span class="summary-value">{{ configSummary.pointCloudTopic || '-' }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Display</span>
          <span class="summary-value">{{ displayCount }} 项</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Grid / Axes</span>
          <span class="summary-value">{{ sceneSummary }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">View</span>
          <span class="summary-value">{{ configSummary.viewPreset }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Layout</span>
          <span class="summary-value">{{ layoutSummary }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Theme</span>
          <span class="summary-value">{{ selectedTheme === 'light' ? '浅色' : '深色' }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useConfigStatusStore } from '../../composables/useConfigStatusStore'
import { configApi } from '../../services/api'
import { systemMessage } from '../../composables/useSystemMessage'

export default {
  name: 'SettingsPanel',
  props: {
    settingsSnapshot: {
      type: Object,
      default: () => ({})
    },
    displaySnapshot: {
      type: Array,
      default: () => []
    }
  },
  emits: [
    'laser-type-change',
    'laser2d-change',
    'pointcloud-change',
    'map-topic-change',
    'odom-topic-change',
    'settings-update',
    'capture-scene-state',
    'config-saved',
    'display-config-apply',
    'fixed-frame-change',
    'follow-frame-change'
  ],
  setup(props, { emit }) {
    const configStatusStore = useConfigStatusStore()
    const startupConfigName = import.meta.env.VITE_RVIZWEB_CONFIG || 'default.rvizweb'
    const configName = ref(startupConfigName)
    const selectedConfigName = ref(startupConfigName)
    const configFiles = ref([])
    const loadedExtensions = ref({})

    const configSummary = computed(() => ({
      fixedFrame: props.settingsSnapshot.fixedFrame || 'map',
      odomTopic: props.settingsSnapshot.position?.odomTopic || '',
      pointCloudTopic: props.settingsSnapshot.laser?.pointCloudTopic || '',
      viewPreset: props.settingsSnapshot.scene?.viewPreset || 'iso'
    }))

    const sceneSummary = computed(() => {
      const scene = props.settingsSnapshot.scene || {}
      const grid = scene.showGrid !== false ? '网格开' : '网格关'
      const axes = scene.showAxes !== false ? '坐标轴开' : '坐标轴关'
      return `${grid} / ${axes}`
    })

    const layoutSummary = computed(() => {
      const sceneWidth = props.settingsSnapshot.layout?.sceneWidth || 68
      const panelCount = Object.keys(props.settingsSnapshot.layout?.panelHeights || {}).length
      const collapsedCount = Object.values(props.settingsSnapshot.layout?.collapsedPanels || {})
        .filter(Boolean).length
      return `点云 ${Math.round(sceneWidth)}% / 高度 ${panelCount || 5} 项 / 折叠 ${collapsedCount} 项`
    })

    const selectedTheme = computed({
      get: () => props.settingsSnapshot.appearance?.theme === 'light' ? 'light' : 'dark',
      set: (theme) => emit('settings-update', { type: 'appearance', theme })
    })

    const displayCount = computed(() => props.displaySnapshot.length)

    const normalizeConfigName = (name) => {
      const trimmed = (name || 'default.rvizweb').trim()
      const withoutOldSuffix = trimmed.endsWith('.rviz') ? trimmed.slice(0, -5) : trimmed
      return withoutOldSuffix.endsWith('.rvizweb') ? withoutOldSuffix : `${withoutOldSuffix}.rvizweb`
    }

    const buildConfig = () => ({
      ...props.settingsSnapshot,
      extensions: JSON.parse(JSON.stringify(loadedExtensions.value || {})),
      displays: props.displaySnapshot.map(display => ({
        name: display.name,
        messageType: display.messageType,
        visible: display.visible,
        config: display.config || {}
      }))
    })

    watch(
      () => [props.settingsSnapshot, props.displaySnapshot],
      () => configStatusStore.updateCurrentConfig(buildConfig()),
      { deep: true, immediate: true }
    )

    const loadConfigFiles = async () => {
      try {
        configFiles.value = await configApi.listConfigs()
      } catch (error) {
        console.warn('Failed to load config list:', error)
      }
    }

    const applyConfig = (config) => {
      const cfg = config || {}
      loadedExtensions.value = cfg.extensions && typeof cfg.extensions === 'object'
        ? JSON.parse(JSON.stringify(cfg.extensions))
        : {}
      emit('fixed-frame-change', cfg.fixedFrame || 'map')
      emit('follow-frame-change', cfg.followFrame || '')

      emit('settings-update', {
        type: 'scene',
        source: 'config',
        showGrid: cfg.scene?.showGrid !== false,
        showAxes: cfg.scene?.showAxes !== false,
        viewPreset: cfg.scene?.viewPreset || 'iso',
        camera: cfg.scene?.camera || null
      })

      emit('settings-update', {
        type: 'layout',
        sceneWidth: cfg.layout?.sceneWidth || 68,
        panelHeights: cfg.layout?.panelHeights || null,
        collapsedPanels: cfg.layout?.collapsedPanels || null
      })

      emit('settings-update', {
        type: 'appearance',
        theme: cfg.appearance?.theme || 'dark'
      })

      emit('settings-update', {
        type: 'video',
        video: cfg.video || {
          sourceUrl: '',
          visible: false,
          layout: { x: null, y: null, width: 360, height: 240 }
        }
      })

      emit('settings-update', {
        type: 'goal',
        goal: cfg.goal || { x: 0, y: 0, z: 0 }
      })

      const position = cfg.position || {}
      emit('odom-topic-change', typeof position.odomTopic === 'string' ? position.odomTopic : '')
      emit('settings-update', {
        type: 'position',
        showRobotModel: position.showRobotModel === true,
        showTrajectory: position.showTrajectory !== false,
        trajectoryLength: position.trajectoryLength || 100
      })
      const laser = cfg.laser || {}
      emit('laser-type-change', laser.laserType || '3d')
      emit('laser2d-change', typeof laser.laserScanTopic === 'string' ? laser.laserScanTopic : '')
      emit('pointcloud-change', typeof laser.pointCloudTopic === 'string' ? laser.pointCloudTopic : '')
      emit('settings-update', {
        type: 'laser',
        showLaserPoints: laser.showLaserPoints !== false,
        showLaserLines: laser.showLaserLines !== false,
        showIntensity: !!laser.showIntensity,
        pointSize: laser.laserPointSize || 0.15
      })
      emit('settings-update', {
        type: 'pointcloud',
        pointSize: laser.pointSize || 0.03,
        opacity: laser.pointOpacity || 0.8,
        showIntensity: !!laser.showIntensity
      })

      const map = cfg.map || {}
      emit('map-topic-change', typeof map.mapTopic === 'string' ? map.mapTopic : '')
      emit('settings-update', {
        type: 'map',
        showMap: map.showMap !== false,
        opacity: map.mapOpacity || 0.8,
        showGrid: !!map.showMapGrid,
        showOrigin: map.showMapOrigin !== false
      })

      if (Array.isArray(cfg.displays)) {
        emit('display-config-apply', cfg.displays)
      }
    }

    const validateConfig = (config) => {
      if (!config || typeof config !== 'object' || Array.isArray(config)) {
        throw new Error('配置主体必须是对象')
      }
      if (typeof config.fixedFrame !== 'string' || !config.fixedFrame.trim()) {
        throw new Error('Fixed Frame 不能为空')
      }
      if (!Array.isArray(config.displays)) {
        throw new Error('Displays 必须是数组')
      }
      config.displays.forEach((display, index) => {
        if (!display || typeof display.name !== 'string' || typeof display.messageType !== 'string') {
          throw new Error(`第 ${index + 1} 个 Display 格式无效`)
        }
      })
      return config
    }

    const saveConfig = async () => {
      try {
        emit('capture-scene-state')
        await nextTick()
        const name = normalizeConfigName(configName.value)
        const config = validateConfig(buildConfig())
        const result = await configApi.saveConfig(name, config)
        configName.value = name
        selectedConfigName.value = name
        configStatusStore.markSaved(name, config, result.modified_at)
        emit('config-saved', config)
        await loadConfigFiles()
        systemMessage.success(`配置已保存: ${name}`)
      } catch (error) {
        systemMessage.fromError(error, '保存配置失败')
      }
    }

    const loadSelectedConfig = async () => {
      if (!selectedConfigName.value) return
      try {
        const data = await configApi.getConfig(selectedConfigName.value)
        const nextConfig = validateConfig(data.config || data)
        applyConfig(nextConfig)
        const loadedName = data.name || selectedConfigName.value
        configName.value = loadedName
        await nextTick()
        configStatusStore.markLoaded(loadedName, buildConfig(), data.modified_at)
        if (data.repaired) {
          systemMessage.success(
            `配置已读取并自动修复 ${data.repairs?.length || 1} 项: ${selectedConfigName.value}`
          )
        } else {
          systemMessage.success(`配置已读取: ${selectedConfigName.value}`)
        }
      } catch (error) {
        const message = systemMessage.getErrorMessage(error, '读取配置失败')
        systemMessage.error(`${message}，当前界面未修改`)
      }
    }

    const deleteSelectedConfig = async () => {
      if (!selectedConfigName.value) return
      try {
        const deletedName = selectedConfigName.value
        await configApi.deleteConfig(deletedName)
        configStatusStore.markDeleted(deletedName)
        systemMessage.success(`配置已删除: ${deletedName}`)
        selectedConfigName.value = ''
        await loadConfigFiles()
      } catch (error) {
        systemMessage.fromError(error, '删除配置失败')
      }
    }

    const loadDefaultConfig = async () => {
      await loadConfigFiles()
      const requestedConfig = normalizeConfigName(startupConfigName)
      if (configFiles.value.includes(requestedConfig)) {
        selectedConfigName.value = requestedConfig
        await loadSelectedConfig()
      } else {
        systemMessage.error(`启动配置不存在: ${requestedConfig}`)
      }
    }

    onMounted(loadDefaultConfig)

    return {
      configName,
      selectedConfigName,
      configFiles,
      configSummary,
      sceneSummary,
      layoutSummary,
      selectedTheme,
      displayCount,
      saveConfig,
      loadSelectedConfig,
      deleteSelectedConfig
    }
  }
}
</script>

<style scoped>
.settings-panel {
  height: 100%;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-elevated);
}

.settings-section {
  border: 1px solid var(--border-muted);
  background: var(--bg-elevated);
  border-radius: var(--radius);
  padding: 12px;
  margin-bottom: 12px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-heading h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}

.section-heading span {
  color: var(--text-muted);
  font-size: 11px;
}

.field-row {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
}

.field-row:last-child {
  margin-bottom: 0;
}

.field-row label {
  color: var(--text-secondary);
  font-size: 12px;
}

.inline-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.config-select {
  flex: 1;
  min-width: 160px;
}

.summary-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.summary-item {
  display: grid;
  gap: 3px;
  padding: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-muted);
  border-radius: var(--radius);
}

.summary-label {
  color: var(--text-muted);
  font-size: 11px;
}

.summary-value {
  color: var(--text-primary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-select .el-input__wrapper),
:deep(.el-input__wrapper) {
  background-color: var(--bg-input) !important;
  border-color: var(--border) !important;
}

:deep(.el-input__inner) {
  color: var(--text-primary) !important;
}

:deep(.el-button) {
  border-color: var(--border) !important;
}
</style>
