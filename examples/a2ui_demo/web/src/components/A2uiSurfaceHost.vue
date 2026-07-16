<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import "@/a2uiMarkdownHost";

const props = defineProps<{
  surface: unknown;
}>();

const hostEl = ref<HTMLElement & { surface?: unknown } | null>(null);

function sync() {
  if (hostEl.value) {
    hostEl.value.surface = props.surface;
  }
}

onMounted(sync);
watch(() => props.surface, sync);
</script>

<template>
  <!--
    Vue 只负责把 SurfaceModel 交给 Web Component。
    真正的 Button / TextField / Card 由官方 @a2ui/lit Catalog 渲染。
  -->
  <a2ui-markdown-host ref="hostEl" />
</template>
