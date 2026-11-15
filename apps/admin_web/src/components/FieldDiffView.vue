<script setup lang="ts">
import type { FieldDiff } from '../compare'
import DiffText from './DiffText.vue'
import MathText from './MathText.vue'

defineProps<{ field: FieldDiff; leftLabel: string; rightLabel: string }>()
</script>

<template>
  <div class="field-diff" :class="{ changed: field.changed }" :data-testid="`field-${field.key}`">
    <h3>
      {{ field.label }}
      <span v-if="field.changed" class="badge badge-draft">有改动</span>
    </h3>
    <div class="columns head muted small">
      <span>{{ leftLabel }}</span>
      <span>{{ rightLabel }}</span>
    </div>

    <template v-if="field.mode === 'text'">
      <div class="columns">
        <div class="cell" :class="{ del: field.changed }">
          <DiffText :segs="field.leftSegs" :text="field.left" />
          <span v-if="!field.left" class="muted">（空）</span>
          <div v-if="field.math && field.left" class="rendered"><MathText :text="field.left" /></div>
        </div>
        <div class="cell" :class="{ add: field.changed }">
          <DiffText :segs="field.rightSegs" :text="field.right" />
          <span v-if="!field.right" class="muted">（空）</span>
          <div v-if="field.math && field.right" class="rendered"><MathText :text="field.right" /></div>
        </div>
      </div>
    </template>

    <template v-else>
      <p v-if="field.rows.length === 0" class="muted small">两个版本都没有。</p>
      <div v-for="(row, index) in field.rows" :key="index" class="columns row" :class="`row-${row.kind}`">
        <div class="cell">
          <template v-if="row.left !== null">
            <DiffText :segs="row.leftSegs" :text="row.left" />
            <div v-if="field.math && row.kind !== 'same'" class="rendered"><MathText :text="row.left" /></div>
          </template>
        </div>
        <div class="cell">
          <template v-if="row.right !== null">
            <DiffText :segs="row.rightSegs" :text="row.right" />
            <div v-if="field.math && row.kind !== 'same'" class="rendered"><MathText :text="row.right" /></div>
          </template>
        </div>
      </div>
    </template>
  </div>
</template>
