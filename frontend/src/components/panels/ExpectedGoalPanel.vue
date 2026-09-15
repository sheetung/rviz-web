<template>
  <div class="expected-goal-panel">
    <div class="goal-grid">
      <label>
        X
        <el-input-number
          :model-value="goal.x"
          size="small"
          :step="0.1"
          :precision="2"
          controls-position="right"
          @update:model-value="value => updateCoordinate('x', value)"
        />
      </label>
      <label>
        Y
        <el-input-number
          :model-value="goal.y"
          size="small"
          :step="0.1"
          :precision="2"
          controls-position="right"
          @update:model-value="value => updateCoordinate('y', value)"
        />
      </label>
      <label>
        Z
        <el-input-number
          :model-value="goal.z"
          size="small"
          :step="0.1"
          :precision="2"
          controls-position="right"
          @update:model-value="value => updateCoordinate('z', value)"
        />
      </label>
    </div>

    <div class="goal-meta">
      <span class="meta-label">Topic</span>
      <el-input
        :model-value="goal.topic"
        size="small"
        placeholder="目标话题"
        @update:model-value="updateTopic"
      />
      <span class="meta-sep"></span>
      <span class="meta-label">Frame</span>
      <strong>{{ fixedFrame || 'map' }}</strong>
      <span class="meta-sep"></span>
      <span class="meta-label">方向</span>
      <strong>+X</strong>
    </div>

    <div class="goal-actions">
      <el-button size="small" @click="resetGoal">重置</el-button>
      <el-button size="small" @click="previewGoal">展示</el-button>
      <el-button size="small" type="primary" @click="publishGoal">
        发布
      </el-button>
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'

const createDefaultGoal = () => ({
  topic: '',
  x: 0,
  y: 0,
  z: 0
})

const normalizeGoal = (goal) => ({
  topic: typeof goal?.topic === 'string' ? goal.topic.trim() : '',
  x: Number(goal?.x) || 0,
  y: Number(goal?.y) || 0,
  z: Number(goal?.z) || 0
})

export default {
  name: 'ExpectedGoalPanel',
  props: {
    goal: {
      type: Object,
      default: () => createDefaultGoal()
    },
    fixedFrame: {
      type: String,
      default: 'map'
    }
  },
  emits: ['goal-update', 'goal-preview', 'goal-publish'],
  setup(props, { emit }) {
    const normalizedGoal = computed(() => normalizeGoal(props.goal))

    const updateCoordinate = (axis, value) => {
      emit('goal-update', {
        ...normalizedGoal.value,
        [axis]: Number(value) || 0
      })
    }

    const updateTopic = (topic) => {
      emit('goal-update', {
        ...normalizedGoal.value,
        topic
      })
    }

    const previewGoal = () => {
      emit('goal-preview', normalizedGoal.value)
    }

    const publishGoal = () => {
      emit('goal-publish', normalizedGoal.value)
    }

    const resetGoal = () => {
      emit('goal-update', createDefaultGoal())
    }

    return {
      normalizedGoal,
      updateCoordinate,
      updateTopic,
      previewGoal,
      publishGoal,
      resetGoal
    }
  }
}
</script>

<style scoped>
.expected-goal-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: var(--bg-elevated);
}

.goal-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.goal-grid label {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 12px;
}

.goal-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--border-muted);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: 12px;
}

.goal-meta .meta-label {
  flex: 0 0 auto;
  color: var(--text-muted);
  font-size: 11px;
}

.goal-meta strong {
  overflow-wrap: anywhere;
  min-width: 0;
  color: var(--text-primary);
  font-weight: 600;
  font-size: 12px;
}

.goal-meta .meta-sep {
  width: 1px;
  height: 14px;
  background: var(--border);
  flex: 0 0 auto;
  margin: 0 2px;
}

.goal-meta :deep(.el-input) {
  flex: 1;
  min-width: 80px;
}

.goal-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: auto;
}

:deep(.el-input-number) {
  width: 100%;
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-input) !important;
  border-color: var(--border) !important;
}

:deep(.el-input__inner) {
  color: var(--text-primary) !important;
}
</style>
