<template>
  <div class="workflow-workspace" data-page-archetype="workflow">
    <UiPageHeader
      :title="title"
      :eyebrow="eyebrow"
      :description="description"
    >
      <template v-if="$slots.actions" #actions>
        <slot name="actions" />
      </template>
      <UiStatusBadge
        v-if="statusLabel"
        class="workflow-workspace-status"
        :label="statusLabel"
        :tone="statusTone"
      />
    </UiPageHeader>

    <UiSurface
      as="div"
      variant="inset"
      padding="lg"
      class="workflow-shell"
    >
      <div v-if="hasWorkflowContent" class="workflow-layout">
        <section
          v-if="$slots.configuration"
          class="workflow-primary"
          data-workflow-slot="configuration"
          aria-label="配置"
        >
          <slot name="configuration" />
        </section>

        <aside class="workflow-secondary" aria-label="工作流进度与结果">
          <section
            v-if="$slots.progress"
            class="workflow-progress"
            data-workflow-slot="progress"
          >
            <slot name="progress" />
          </section>
          <section
            v-if="$slots.result"
            class="workflow-result"
            data-workflow-slot="result"
          >
            <slot name="result" />
          </section>
        </aside>

        <section
          v-if="$slots.resources"
          class="workflow-resources"
          data-workflow-slot="resources"
          aria-label="相关资源"
        >
          <slot name="resources" />
        </section>
      </div>
      <UiStatePanel
        v-else
        state="empty"
        title="暂无工作流内容"
        message="此工作区尚未提供配置或运行信息。"
      />
    </UiSurface>
  </div>
</template>

<script setup>
import { computed, useSlots } from 'vue'
import UiPageHeader from '../ui/UiPageHeader.vue'
import UiStatePanel from '../ui/UiStatePanel.vue'
import UiStatusBadge from '../ui/UiStatusBadge.vue'
import UiSurface from '../ui/UiSurface.vue'

const WORKFLOW_STATUS_TONES = Object.freeze([
  'neutral',
  'info',
  'success',
  'warning',
  'danger',
])

defineProps({
  title: { type: String, required: true },
  eyebrow: { type: String, default: '' },
  description: { type: String, default: '' },
  statusLabel: { type: String, default: '' },
  statusTone: {
    type: String,
    default: 'neutral',
    validator: value => WORKFLOW_STATUS_TONES.includes(value),
  },
})

const slots = useSlots()
const hasWorkflowContent = computed(() => [
  'configuration',
  'progress',
  'result',
  'resources',
].some(name => Boolean(slots[name])))
</script>

<style scoped>
.workflow-workspace {
  --workflow-shell-gap: 1rem;
  --workflow-column-gap: clamp(1rem, 2.5vw, 1.5rem);
  --workflow-secondary-min: 18rem;
  min-width: 0;
  color: var(--text-main);
}

.workflow-workspace-status {
  margin-top: .6rem;
}

.workflow-shell {
  min-width: 0;
  background: var(--surface-inset);
}

.workflow-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(var(--workflow-secondary-min), .85fr);
  gap: var(--workflow-column-gap);
  align-items: start;
}

.workflow-primary,
.workflow-secondary,
.workflow-resources {
  min-width: 0;
}

.workflow-primary {
  grid-column: 1;
}

.workflow-secondary {
  display: grid;
  grid-column: 2;
  gap: var(--workflow-shell-gap);
  align-content: start;
}

.workflow-progress,
.workflow-result {
  min-width: 0;
}

.workflow-resources {
  grid-column: 1 / -1;
}

@media (max-width: 767px) {
  .workflow-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .workflow-primary,
  .workflow-secondary,
  .workflow-resources {
    grid-column: 1;
  }

  .workflow-secondary {
    gap: var(--workflow-shell-gap);
  }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-workspace * {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
  }
}
</style>
