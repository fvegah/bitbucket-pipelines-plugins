<script setup>
import { onMounted, ref } from 'vue'
import Icon from './Icon.vue'

defineProps({ title: { type: String, required: true } })
const emit = defineEmits(['close'])
const dlg = ref(null)
onMounted(() => dlg.value.showModal())
</script>

<template>
  <dialog ref="dlg" class="modal" @cancel.prevent="emit('close')" @click.self="emit('close')">
    <div class="modal-head">
      <h2>{{ title }}</h2>
      <button class="btn icon ghost" aria-label="Cerrar" @click="emit('close')"><Icon name="plus" style="transform: rotate(45deg)" /></button>
    </div>
    <slot />
  </dialog>
</template>
