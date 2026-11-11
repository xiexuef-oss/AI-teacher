<script setup lang="ts">
import katex from 'katex'
import { computed } from 'vue'
import { splitMath } from '../math'

const props = defineProps<{ text: string }>()

interface Part {
  math: boolean
  text: string
  html: string
}

// 公式只经过 KaTeX（不信任 \href 之类的扩展），其余文字走普通文本节点，不会被当成 HTML。
const parts = computed<Part[]>(() =>
  splitMath(props.text).map((segment) => ({
    math: segment.math,
    text: segment.text,
    html: segment.math
      ? katex.renderToString(segment.text, { throwOnError: false, strict: 'ignore', output: 'html' })
      : '',
  })),
)
</script>

<template>
  <span class="math-text">
    <template v-for="(part, index) in parts" :key="index">
      <span v-if="part.math" class="math" v-html="part.html" />
      <template v-else>{{ part.text }}</template>
    </template>
  </span>
</template>
