<template>
  <UiSurface
    as="section"
    class="workflow-stage"
    :class="`workflow-stage-${name}`"
    variant="panel"
    padding="lg"
    :labelledby="headingId"
    :aria-describedby="description ? descriptionId : undefined"
    :data-workflow-stage="name"
    :data-workflow-state="state"
  >
    <template #header>
      <div class="workflow-stage-header">
        <div class="workflow-stage-copy">
          <p class="workflow-stage-name">{{ stageLabel }}</p>
          <h2 :id="headingId" class="workflow-stage-title">{{ title }}</h2>
          <p v-if="description" :id="descriptionId" class="workflow-stage-description">{{ description }}</p>
        </div>
        <div class="workflow-stage-controls">
          <UiStatusBadge
            v-if="state !== 'idle'"
            :tone="stateTone"
            :label="stateLabel"
          />
          <div v-if="$slots.actions" class="workflow-stage-actions">
            <slot name="actions" />
          </div>
        </div>
      </div>
    </template>

    <div v-if="$slots.default" class="workflow-stage-content">
      <slot />
    </div>
    <UiStatePanel
      v-else
      :state="statePanelState"
      :title="statePanelTitle"
      :message="statePanelMessage"
    />
  </UiSurface>
</template>

<script setup>
import { computed } from 'vue'
import UiStatePanel from '../ui/UiStatePanel.vue'
import UiStatusBadge from '../ui/UiStatusBadge.vue'
import UiSurface from '../ui/UiSurface.vue'

const WORKFLOW_STAGE_NAMES = Object.freeze([
  'configuration',
  'launch',
  'progress',
  'result',
  'resources',
])

const WORKFLOW_STAGE_STATES = Object.freeze([
  'idle',
  'active',
  'complete',
  'warning',
  'error',
])

const STAGE_LABELS = Object.freeze({
  configuration: '配置',
  launch: '启动',
  progress: '进度',
  result: '结果',
  resources: '资源',
})

const STATE_LABELS = Object.freeze({
  idle: '未开始',
  active: '进行中',
  complete: '已完成',
  warning: '需注意',
  error: '失败',
})

const STATE_TONES = Object.freeze({
  active: 'info',
  complete: 'success',
  warning: 'warning',
  error: 'danger',
})

const STATE_PANEL_STATES = Object.freeze({
  idle: 'empty',
  active: 'loading',
  complete: 'empty',
  warning: 'partial',
  error: 'error',
})

const props = defineProps({
  name: {
    type: String,
    required: true,
    validator: value => WORKFLOW_STAGE_NAMES.includes(value),
  },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  state: {
    type: String,
    default: 'idle',
    validator: value => WORKFLOW_STAGE_STATES.includes(value),
  },
})

const headingId = computed(() => `workflow-stage-${props.name}-heading`)
const descriptionId = computed(() => `${headingId.value}-description`)
const stageLabel = computed(() => STAGE_LABELS[props.name])
const stateLabel = computed(() => STATE_LABELS[props.state])
const stateTone = computed(() => STATE_TONES[props.state] || 'neutral')
const statePanelState = computed(() => STATE_PANEL_STATES[props.state] || 'empty')
const statePanelTitle = computed(() => {
  if (props.state === 'active') return `${stageLabel.value}正在进行`
  if (props.state === 'complete') return `${stageLabel.value}已完成`
  if (props.state === 'warning') return `${stageLabel.value}需要关注`
  if (props.state === 'error') return `${stageLabel.value}执行失败`
  return `等待${stageLabel.value}`
})
const statePanelMessage = computed(() => {
  if (props.state === 'active') return '状态会在任务推进时更新。'
  if (props.state === 'complete') return '该阶段已完成，暂无更多内容。'
  if (props.state === 'warning') return '请检查当前阶段的提示信息。'
  if (props.state === 'error') return '请查看错误详情并重试。'
  return '准备好后，相关内容会显示在这里。'
})
</script>

<style scoped>
.workflow-stage {
  --workflow-stage-gap: .85rem;
  --workflow-stage-heading-size: 1.05rem;
  --workflow-stage-name-size: .68rem;
  --workflow-stage-description-size: .8rem;
  min-width: 0;
  color: var(--text-main);
}

.workflow-stage-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--workflow-stage-gap);
}

.workflow-stage-copy {
  min-width: 0;
}

.workflow-stage-name {
  margin: 0 0 .25rem;
  color: var(--accent-text);
  font-size: var(--workflow-stage-name-size);
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.workflow-stage-title {
  margin: 0;
  color: var(--text-main);
  font-size: var(--workflow-stage-heading-size);
  font-weight: 700;
  letter-spacing: -.015em;
}

.workflow-stage-description {
  margin: .35rem 0 0;
  color: var(--text-muted);
  font-size: var(--workflow-stage-description-size);
  line-height: 1.5;
}

.workflow-stage-controls {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: .5rem;
}

.workflow-stage-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: .5rem;
}

.workflow-stage-content {
  min-width: 0;
}

@media (max-width: 520px) {
  .workflow-stage-header {
    flex-direction: column;
  }

  .workflow-stage-controls,
  .workflow-stage-actions {
    justify-content: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-stage * {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
  }
}
</style>
