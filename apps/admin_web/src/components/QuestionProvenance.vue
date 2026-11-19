<script setup lang="ts">
import type { components } from '../api/schema'

defineProps<{ provenance?: components['schemas']['QuestionProvenance'] | null }>()
const locationLabels: Record<components['schemas']['QuestionOriginLocation']['locator_kind'], string> = {
  pdf_page: 'PDF 物理页', word_fragment: 'Word 有序片段', image_page: '图片页',
  json_fragment: 'JSON 片段', unknown: '未知位置序号',
}
</script>

<template>
  <aside class="card" data-testid="question-provenance">
    <h2>此版本的导入来源定位</h2>
    <p v-if="!provenance" class="muted">暂无导入定位记录</p>
    <template v-else>
      <p>来源快照：{{ provenance.source_snapshot.label }}</p>
      <dl>
        <dt>工程样题</dt><dd>{{ provenance.source_snapshot.is_engineering_sample ? '是（不代表已通过学科审校）' : '否' }}</dd>
        <dt>来源名称</dt><dd>{{ provenance.source_snapshot.source_name ?? '未声明' }}</dd>
        <dt>来源类型 / 类别</dt><dd>{{ provenance.source_snapshot.source_type }} / {{ provenance.source_snapshot.source_category }}</dd>
        <dt>年份</dt><dd>{{ provenance.source_snapshot.source_year ?? '未声明' }}</dd>
        <dt>许可声明</dt><dd>{{ provenance.source_snapshot.source_license }}</dd>
        <dt>来源网址声明</dt><dd>{{ provenance.source_snapshot.source_url ?? '未声明' }}</dd>
      </dl>
      <p>{{ provenance.relation === 'declared' ? '导入时声明' : '编辑派生，未重新验证' }}<span v-if="provenance.parent_version !== null"> · 父版本：{{ provenance.parent_version }}</span></p>
      <ul>
        <li v-for="(origin, position) in provenance.origins" :key="position">
          {{ locationLabels[origin.locator_kind] }} {{ origin.index }} · 格式：{{ origin.file_kind }}
          <span v-if="origin.declared_block !== null"> · 声明块序 {{ origin.declared_block }}（未精确验证）</span>
          <div class="digest">SHA-256：{{ origin.file_sha256 }}</div>
        </li>
      </ul>
      <p class="muted">仅元数据（{{ provenance.access }}）；来源位置和块序为声明，未精确验证，不代表版权已审或精确引文。原文件按独立的临时期限管理，本记录不提供预览或下载。</p>
    </template>
  </aside>
</template>

<style scoped>
.digest { overflow-wrap: anywhere; }
dd { overflow-wrap: anywhere; }
</style>

