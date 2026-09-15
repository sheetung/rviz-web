<template>
  <div id="app">
    <div class="app-header">
      <div class="header-left">
        <div class="app-logo">
          <div class="logo-icon"></div>
          <div class="app-identity">
            <h1 class="app-title">{{ appTitle }}</h1>
            <span class="app-subtitle">ROS Workbench</span>
          </div>
        </div>
      </div>
      <div class="header-right">
        <connection-status />
      </div>
    </div>

    <div class="app-content">
      <router-view />
    </div>
  </div>
</template>

<script>
import { onMounted, onUnmounted } from 'vue'
import ConnectionStatus from './components/common/ConnectionStatus.vue'
import { useConnectionStore } from './composables/useConnectionStore'

export default {
  name: 'App',
  components: {
    ConnectionStatus
  },
  setup() {
    const connectionStore = useConnectionStore()
    const appTitle = String(import.meta.env.VITE_APP_TITLE || 'RVizWeb').trim() || 'RVizWeb'

    onMounted(() => {
      connectionStore.initializeConnection()
    })

    onUnmounted(() => {
      connectionStore.disconnect()
    })

    return { appTitle }
  }
}
</script>

<style>
:root {
  --bg-app: #0d1117;
  --bg-surface: #0f141a;
  --bg-panel: #151b22;
  --bg-header: #1c232b;
  --bg-elevated: #111820;
  --bg-input: #121820;
  --border: #2d3742;
  --border-strong: #425161;
  --border-muted: #27313d;
  --text-primary: #e5edf5;
  --text-secondary: #9aa8b5;
  --text-muted: #8292a3;
  --accent: #46bdf0;
  --accent-strong: #00d4ff;
  --accent-soft: #172532;
  --success: #3dd68c;
  --warning: #f0b429;
  --danger: #f07178;
  --info: #74b9ff;
  --radius: 6px;
  --radius-sm: 4px;
  --header-h: 48px;
  --panel-header-h: 30px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --handle: #33404c;
  --handle-hover: #5c7a95;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.25);
  --scrollbar-thumb: #3a4652;
  --bg-hover: #24303a;
  --bg-active: #1a232c;
  --accent-dark: #1782a8;
  --accent-mid: #1b95c0;
  --accent-glow: #9ee7ff;
  --text-inverse: #ffffff;
  --bg-subtle: rgba(148, 163, 184, 0.1);
  --border-subtle: rgba(148, 163, 184, 0.15);
  --radius-md: 6px;

  /* Translucent surfaces and effects */
  --surface-glass: rgba(15, 23, 42, 0.8);
  --surface-glass-strong: rgba(15, 23, 42, 0.9);
  --surface-glass-solid: rgba(15, 23, 42, 0.95);
  --surface-glass-muted: rgba(15, 23, 42, 0.6);
  --surface-glass-soft: rgba(15, 23, 42, 0.4);
  --surface-glass-faint: rgba(15, 23, 42, 0.3);
  --surface-chart: rgba(0, 0, 0, 0.8);
  --surface-overlay: rgba(12, 17, 23, 0.82);
  --surface-tooltip: rgba(0, 0, 0, 0.7);
  --surface-hint: rgba(0, 0, 0, 0.58);
  --neutral-05: rgba(148, 163, 184, 0.05);
  --neutral-10: rgba(148, 163, 184, 0.1);
  --neutral-15: rgba(148, 163, 184, 0.15);
  --neutral-20: rgba(148, 163, 184, 0.2);
  --neutral-30: rgba(148, 163, 184, 0.3);
  --neutral-40: rgba(148, 163, 184, 0.4);
  --neutral-60: rgba(148, 163, 184, 0.6);
  --text-inverse-muted: rgba(255, 255, 255, 0.8);
  --text-inverse-faint: rgba(255, 255, 255, 0.3);
  --shadow-color-10: rgba(0, 0, 0, 0.1);
  --shadow-color-20: rgba(0, 0, 0, 0.2);
  --shadow-color-30: rgba(0, 0, 0, 0.3);
  --shadow-color-35: rgba(0, 0, 0, 0.35);
  --shadow-color-50: rgba(0, 0, 0, 0.5);

  /* Semantic visualization colors */
  --viz-blue: #3b82f6;
  --viz-blue-10: rgba(59, 130, 246, 0.1);
  --viz-blue-20: rgba(59, 130, 246, 0.2);
  --viz-blue-30: rgba(59, 130, 246, 0.3);
  --viz-blue-40: rgba(59, 130, 246, 0.4);
  --viz-cyan: #06b6d4;
  --viz-cyan-20: rgba(6, 182, 212, 0.2);
  --viz-cyan-30: rgba(6, 182, 212, 0.3);
  --viz-green: #22c55e;
  --viz-green-10: rgba(34, 197, 94, 0.1);
  --viz-green-20: rgba(34, 197, 94, 0.2);
  --viz-green-30: rgba(34, 197, 94, 0.3);
  --viz-green-40: rgba(34, 197, 94, 0.4);
  --viz-orange: #f59e0b;
  --viz-orange-10: rgba(245, 158, 11, 0.1);
  --viz-orange-15: rgba(245, 158, 11, 0.15);
  --viz-orange-20: rgba(245, 158, 11, 0.2);
  --viz-orange-30: rgba(245, 158, 11, 0.3);
  --viz-purple: #8b5cf6;
  --viz-purple-20: rgba(139, 92, 246, 0.2);
  --viz-purple-30: rgba(139, 92, 246, 0.3);
  --viz-lime: #84cc16;
  --viz-lime-20: rgba(132, 204, 22, 0.2);
  --viz-lime-30: rgba(132, 204, 22, 0.3);
  --viz-deep-orange: #f97316;
  --viz-deep-orange-20: rgba(249, 115, 22, 0.2);
  --viz-deep-orange-30: rgba(249, 115, 22, 0.3);
  --viz-pink: #ec4899;
  --viz-pink-20: rgba(236, 72, 153, 0.2);
  --viz-pink-30: rgba(236, 72, 153, 0.3);
  --viz-red: #ef4444;
  --accent-strong-20: rgba(0, 212, 255, 0.2);
  --accent-strong-30: rgba(0, 212, 255, 0.3);
  --accent-strong-50: rgba(0, 212, 255, 0.5);
  --danger-soft: rgba(240, 113, 120, 0.18);
  --success-soft: rgba(61, 214, 140, 0.1);
  --success-glow: rgba(61, 214, 140, 0.5);
  --warning-soft: rgba(240, 180, 41, 0.1);
  --danger-surface: rgba(240, 113, 120, 0.1);
  --muted-surface: rgba(130, 146, 163, 0.1);

  /* Chart palette and 3D axes */
  --chart-series-1: #409eff;
  --chart-series-2: #67c23a;
  --chart-series-3: #e6a23c;
  --chart-series-4: #f56c6c;
  --chart-series-5: #909399;
  --chart-series-6: #00d4ff;
  --chart-series-7: #00ff88;
  --chart-series-8: #ffaa00;
  --chart-series-9: #ff4757;
  --chart-series-10: #74b9ff;
  --chart-series-11: #fd79a8;
  --chart-series-12: #a29bfe;
  --chart-series-13: #6c5ce7;
  --chart-series-14: #00b894;
  --chart-series-15: #00cec9;
  --axis-x: #ff0000;
  --axis-y: #00ff00;
  --axis-z: #0000ff;
  --scene-background: #2c3e50;

  --el-color-primary: var(--accent-strong);
  --el-color-success: var(--success);
  --el-color-warning: var(--warning);
  --el-color-danger: var(--danger);
  --el-color-info: var(--info);

  --el-bg-color: var(--bg-panel);
  --el-bg-color-page: var(--bg-app);
  --el-bg-color-overlay: var(--bg-header);

  --el-text-color-primary: var(--text-primary);
  --el-text-color-regular: var(--text-primary);
  --el-text-color-secondary: var(--text-secondary);
  --el-text-color-placeholder: var(--text-muted);

  --el-border-color: var(--border);
  --el-border-color-light: var(--border-muted);
  --el-border-color-lighter: var(--border-muted);
  --el-border-color-extra-light: var(--border-muted);
  --el-border-radius-base: var(--radius-sm);
  --el-fill-color-blank: var(--bg-input);
}

:root[data-theme='light'] {
  color-scheme: light;
  --bg-app: #f3f6f9;
  --bg-surface: #e9eef3;
  --bg-panel: #ffffff;
  --bg-header: #f5f7fa;
  --bg-elevated: #f8fafc;
  --bg-input: #ffffff;
  --border: #cbd5df;
  --border-strong: #91a2b3;
  --border-muted: #dbe3ea;
  --text-primary: #17212b;
  --text-secondary: #526170;
  --text-muted: #718096;
  --accent: #087ea4;
  --accent-strong: #007fa3;
  --accent-soft: #dff3fb;
  --success: #168a55;
  --warning: #9a6700;
  --danger: #c93745;
  --info: #2368a2;
  --handle: #aab8c5;
  --handle-hover: #6f879c;
  --scrollbar-thumb: #9eacb9;
  --bg-hover: #e5edf4;
  --bg-active: #dbe6ef;
  --accent-dark: #086b8c;
  --accent-mid: #087ea4;
  --accent-glow: #075f7c;
  --bg-subtle: rgba(71, 85, 105, 0.08);
  --border-subtle: rgba(71, 85, 105, 0.18);
  --surface-glass: rgba(255, 255, 255, 0.88);
  --surface-glass-strong: rgba(255, 255, 255, 0.94);
  --surface-glass-solid: rgba(255, 255, 255, 0.98);
  --surface-glass-muted: rgba(255, 255, 255, 0.76);
  --surface-glass-soft: rgba(255, 255, 255, 0.64);
  --surface-glass-faint: rgba(255, 255, 255, 0.52);
  --surface-chart: #ffffff;
  --surface-overlay: rgba(248, 250, 252, 0.9);
  --neutral-05: rgba(71, 85, 105, 0.05);
  --neutral-10: rgba(71, 85, 105, 0.1);
  --neutral-15: rgba(71, 85, 105, 0.15);
  --neutral-20: rgba(71, 85, 105, 0.2);
  --neutral-30: rgba(71, 85, 105, 0.3);
  --neutral-40: rgba(71, 85, 105, 0.4);
  --neutral-60: rgba(71, 85, 105, 0.6);
  --success-soft: rgba(22, 138, 85, 0.1);
  --success-glow: rgba(22, 138, 85, 0.35);
  --warning-soft: rgba(154, 103, 0, 0.1);
  --danger-surface: rgba(201, 55, 69, 0.1);
  --muted-surface: rgba(113, 128, 150, 0.1);
  --scene-background: #edf2f7;
}

:root:not([data-theme]),
:root[data-theme='dark'] {
  color-scheme: dark;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body {
  font-family: 'Segoe UI', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg-app);
  color: var(--text-primary);
  overflow: auto;
}

#app {
  height: 100vh;
  background: var(--bg-app);
  position: relative;
}

.app-header {
  height: var(--header-h);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  position: relative;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
}

.app-logo {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.logo-icon {
  width: 28px;
  height: 28px;
  background: var(--accent-soft);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  position: relative;
}

.logo-icon::before {
  content: '';
  position: absolute;
  top: 5px;
  left: 5px;
  right: 5px;
  bottom: 5px;
  border: 2px solid var(--accent);
  border-radius: 3px;
}

.logo-icon::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 6px;
  height: 6px;
  background: var(--accent-glow);
  border-radius: 50%;
  transform: translate(-50%, -50%);
}

.app-identity {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.app-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1;
}

.app-subtitle {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 15px;
}

.app-content {
  height: calc(100vh - var(--header-h));
  position: relative;
  z-index: 2;
  overflow: auto;
}

::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: var(--bg-elevated);
  border-radius: var(--radius);
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--handle-hover);
  background-clip: content-box;
}

::-webkit-scrollbar-corner {
  background: var(--bg-elevated);
}

.el-card {
  background: var(--bg-panel) !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
}

.el-button {
  --el-button-bg-color: var(--bg-header);
  --el-button-border-color: var(--border);
  --el-button-text-color: var(--text-primary);
  --el-button-hover-bg-color: var(--bg-hover);
  --el-button-hover-border-color: var(--border-strong);
  --el-button-hover-text-color: var(--text-primary);
  --el-button-active-bg-color: var(--bg-active);
  --el-button-active-border-color: var(--border-strong);
}

.el-button--primary {
  --el-button-bg-color: var(--accent-dark);
  --el-button-border-color: var(--accent-mid);
  --el-button-text-color: var(--text-inverse);
  --el-button-hover-bg-color: var(--accent-mid);
  --el-button-hover-border-color: var(--accent);
  --el-button-hover-text-color: var(--text-inverse);
  --el-button-active-bg-color: var(--accent-dark);
  --el-button-active-border-color: var(--accent-dark);
}

.el-button--success {
  --el-button-bg-color: color-mix(in srgb, var(--success) 60%, var(--bg-app));
  --el-button-border-color: color-mix(in srgb, var(--success) 75%, var(--bg-app));
  --el-button-hover-bg-color: color-mix(in srgb, var(--success) 75%, var(--bg-app));
  --el-button-hover-border-color: var(--success);
}

.el-input__wrapper {
  background: var(--bg-input) !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
}

.el-input__wrapper:hover,
.el-input__wrapper.is-focus {
  border-color: var(--border-strong) !important;
}

.el-select .el-input__wrapper {
  background: var(--bg-input) !important;
}

.el-popper.is-light,
.el-popper {
  background: var(--bg-header) !important;
  border: 1px solid var(--border) !important;
  box-shadow: 0 8px 24px var(--shadow-color-35) !important;
  color: var(--text-primary) !important;
}

.el-dropdown-menu {
  background: var(--bg-header) !important;
  border: 1px solid var(--border) !important;
}

.el-dropdown-menu__item {
  color: var(--text-primary) !important;
}

.el-dropdown-menu__item:not(.is-disabled):hover {
  background: var(--bg-hover) !important;
  color: var(--accent) !important;
}
</style>
