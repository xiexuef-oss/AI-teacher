<script setup lang="ts">
// 一组字符串的编辑器：每项一个文本框，可以增删。用在提示、解法步骤、方法要点、适用条件、泄题标记。
const model = defineModel<string[]>({ required: true })
defineProps<{ label: string; addLabel?: string; rows?: number }>()

function update(index: number, value: string): void {
  model.value = model.value.map((item, i) => (i === index ? value : item))
}

function remove(index: number): void {
  model.value = model.value.filter((_, i) => i !== index)
}

function add(): void {
  model.value = [...model.value, '']
}
</script>

<template>
  <div class="string-list">
    <p class="small"><strong>{{ label }}</strong></p>
    <div v-for="(item, index) in model" :key="index" class="string-row">
      <span class="muted small index">{{ index + 1 }}.</span>
      <textarea
        :value="item"
        :rows="rows ?? 2"
        :aria-label="`${label} ${index + 1}`"
        @input="update(index, ($event.target as HTMLTextAreaElement).value)"
      />
      <button type="button" class="link" :aria-label="`删除${label} ${index + 1}`" @click="remove(index)">
        删除
      </button>
    </div>
    <button type="button" data-testid="add-item" @click="add">{{ addLabel ?? '添加一项' }}</button>
  </div>
</template>
