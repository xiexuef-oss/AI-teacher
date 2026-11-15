<script setup lang="ts">
import type { Seg } from '../diff'

// 一段带差异标记的文本：删掉的片段（del）、新加的片段（add）、没变的片段。没有片段时显示原文。
defineProps<{ segs: Seg[] | null; text?: string | null }>()
</script>

<template>
  <span class="diff-text">
    <template v-if="segs && segs.length">
      <span v-for="(seg, index) in segs" :key="index" :class="`seg-${seg.kind}`">{{ seg.text }}</span>
    </template>
    <template v-else>{{ text }}</template>
  </span>
</template>
