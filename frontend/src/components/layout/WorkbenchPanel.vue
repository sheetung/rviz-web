<template>
  <section
    class="workbench-panel"
    :class="[panelClass, { 'is-collapsed': isCollapsed, 'is-collapsible': collapsible }]"
  >
    <header
      class="workbench-panel-header"
      :class="{ clickable: collapsible }"
      @click="onHeaderClick"
    >
      <h5>{{ title }}</h5>
      <button
        v-if="collapsible"
        type="button"
        class="collapse-btn"
        :title="isCollapsed ? '展开' : '折叠'"
        :aria-expanded="(!isCollapsed).toString()"
        @click.stop="toggleCollapsed"
      >
        <el-icon :size="12">
          <ArrowRight v-if="isCollapsed" />
          <ArrowDown v-else />
        </el-icon>
      </button>
    </header>

    <div v-show="!isCollapsed" class="workbench-panel-content">
      <slot />
    </div>
  </section>
</template>

<script>
import { computed } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'

export default {
  name: 'WorkbenchPanel',
  components: {
    ArrowDown,
    ArrowRight
  },
  props: {
    id: {
      type: String,
      required: true
    },
    title: {
      type: String,
      required: true
    },
    panelClass: {
      type: [String, Array, Object],
      default: ''
    },
    collapsible: {
      type: Boolean,
      default: false
    },
    collapsed: {
      type: Boolean,
      default: undefined
    },
    defaultCollapsed: {
      type: Boolean,
      default: false
    }
  },
  emits: ['update:collapsed', 'collapse-change'],
  data() {
    return {
      localCollapsed: this.defaultCollapsed
    }
  },
  setup(props) {
    const isControlled = computed(() => typeof props.collapsed === 'boolean')

    return { isControlled }
  },
  computed: {
    isCollapsed() {
      if (this.isControlled) return this.collapsed
      return this.localCollapsed
    }
  },
  methods: {
    toggleCollapsed() {
      if (!this.collapsible) return
      const next = !this.isCollapsed
      if (!this.isControlled) {
        this.localCollapsed = next
      }
      this.$emit('update:collapsed', next)
      this.$emit('collapse-change', { id: this.id, collapsed: next })
    },
    onHeaderClick() {
      if (this.collapsible) {
        this.toggleCollapsed()
      }
    }
  }
}
</script>

<style scoped>
.workbench-panel {
  min-width: 200px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 0.2s ease;
  position: relative;
}

.workbench-panel:hover {
  border-color: var(--border-strong);
}

.workbench-panel.is-collapsed {
  flex: 0 0 auto !important;
  height: auto !important;
  min-height: 0 !important;
}

.workbench-panel-header {
  height: var(--panel-header-h);
  flex: 0 0 var(--panel-header-h);
  background: var(--bg-header);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
    gap: 6px;
    padding: 0 8px;
    user-select: none;
  }

  .workbench-panel-content {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 8px;
}

.workbench-panel-header.clickable:hover h5 {
  color: var(--accent);
}

.workbench-panel-header h5 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.15s ease;
}

.collapse-btn {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0;
}

.collapse-btn:hover {
  color: var(--accent);
  border-color: var(--border);
  background: var(--bg-panel);
}

.workbench-panel-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-2);
}

</style>
