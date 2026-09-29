<script setup>
defineProps({
  provider: { type: String, required: true },
  size: { type: Number, default: 16 },
})
</script>

<template>
  <svg v-if="provider === 'github'" class="prov" :width="size" :height="size" viewBox="0 0 16 16" role="img" aria-label="GitHub">
    <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/>
  </svg>
  <svg v-else-if="provider === 'cloudflare'" class="prov cf" :width="size" :height="size" viewBox="0 0 16 16" role="img" aria-label="Cloudflare">
    <path fill="currentColor" d="M10.9 11.6l.2-.6c.2-.7.1-1.3-.2-1.7-.3-.4-.8-.6-1.4-.6L3.6 8.6c-.1 0-.1 0-.2-.1v-.1c0-.1.1-.1.2-.2l5.6-.1c.7 0 1.4-.6 1.7-1.2l.3-.9v-.2A3.7 3.7 0 0 0 4 5.5 1.7 1.7 0 0 0 1.3 7.2C.5 7.3 0 8 0 8.8c0 .1 0 .2.1.3 0 .1.1.1.1.1h10.3c.2 0 .3-.1.4-.3zM12.7 7.8h-.3l-.1.1-.2.6c-.2.7-.1 1.3.2 1.7.3.4.8.6 1.4.6l1.2.1c.1 0 .1 0 .2.1v.2c0 .1-.1.1-.2.2l-1.3.1c-.7 0-1.4.6-1.7 1.2l-.1.3c0 .1 0 .1.1.1H15l.1-.1c.2-.5.3-.9.3-1.4 0-2-1.5-3.6-3.4-3.8z"/>
  </svg>
  <svg v-else class="prov bb" :width="size" :height="size" viewBox="0 0 16 16" role="img" aria-label="Bitbucket">
    <path fill="currentColor" d="M.78 1.21a.5.5 0 00-.5.58l2.14 12.99c.05.33.34.57.67.57h10.25a.5.5 0 00.5-.42l2.14-13.14a.5.5 0 00-.5-.58H.78zm9.01 9.39H6.26l-.96-5h5.35l-.86 5z"/>
  </svg>
</template>

<style scoped>
.prov { flex: none; color: var(--text); }
.bb { color: #2684ff; }
.cf { color: #c75400; }
:root[data-theme='dark'] .cf { color: #f6821f; }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .cf { color: #f6821f; } }
:root[data-theme='dark'] .bb { color: #4c9aff; }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .bb { color: #4c9aff; } }
</style>
