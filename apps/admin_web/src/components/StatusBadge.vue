<script setup lang="ts">
import type { QuestionStatus } from '../api/types'
import { STATUS_LABEL } from '../decisions'

defineProps<{ status: QuestionStatus }>()
</script>

<template>
  <span class="badge" :class="`badge-${status}`">{{ STATUS_LABEL[status] }}</span>
</template>
