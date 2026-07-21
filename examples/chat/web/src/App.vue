<script setup lang="ts">
import { ref } from "vue";
import ChatPanel from "@/components/ChatPanel.vue";
import ScenarioLab from "@/components/ScenarioLab.vue";

type Mode = "chat" | "lab";

const mode = ref<Mode>("chat");
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell-chat': mode === 'chat' }">
    <nav class="mode-nav">
      <button
        type="button"
        :class="{ active: mode === 'chat' }"
        @click="mode = 'chat'"
      >
        Agent 对话
      </button>
      <button
        type="button"
        :class="{ active: mode === 'lab' }"
        @click="mode = 'lab'"
      >
        A2UI 场景实验室
      </button>
    </nav>

    <ChatPanel v-if="mode === 'chat'" />
    <ScenarioLab v-else />
  </div>
</template>
