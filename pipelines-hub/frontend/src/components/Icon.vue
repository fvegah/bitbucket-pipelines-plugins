<script setup>
const PATHS = {
  refresh: 'M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3',
  external: 'M9 2.5h4.5V7M13.5 2.5 7.5 8.5M12 9.5v3.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7',
  branch: 'M5 3v10M5 13a1.5 1.5 0 1 0 0-.01M5 3a1.5 1.5 0 1 0 0 .01M11 5a1.5 1.5 0 1 0 0-.01M11 6.5c0 2.5-6 2-6 5',
  commit: 'M1.5 8h4M10.5 8h4M8 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  clock: 'M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM8 4.5V8l2.5 1.5',
  user: 'M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 14.5c.6-2.6 2.8-4 5.5-4s4.9 1.4 5.5 4',
  search: 'M7 12.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11zM14.5 14.5l-3.6-3.6',
  sun: 'M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1',
  moon: 'M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7z',
  system: 'M2 3h12v8H2zM6 14h4M8 11v3',
  plus: 'M8 3v10M3 8h10',
  trash: 'M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 9h5.8l.6-9',
  chevron: 'M6 4l4 4-4 4',
  down: 'M4 6l4 4 4-4',
  stop: 'M4.5 4.5h7v7h-7z',
  play: 'M5 3.5v9l7-4.5z',
  wrap: 'M2 4h12M2 8h9a2 2 0 0 1 0 4H8m0 0 1.5-1.5M8 12l1.5 1.5M2 12h3',
  download: 'M8 2v8.5M4.5 7 8 10.5 11.5 7M2.5 13.5h11',
  follow: 'M8 2v11M4 9l4 4 4-4',
  gear: 'M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM13 8l1.3-.9-1-2.2-1.6.3-1-1-.2-1.6H8.3l-.5 1.5-1.3.4L5 3.5 3.3 5l.8 1.4-.4 1.3L2.2 8l.3 2.3 1.5.4.5 1.3-.8 1.4 1.7 1.3 1.3-.9 1.3.4.4 1.5h2.2l.3-1.6 1.2-.6 1.5.6 1.3-1.8-1-1.3z',
  repo: 'M3.5 13.5v-11a1 1 0 0 1 1-1h8v10h-8a1 1 0 0 0-1 1zm0 0a1 1 0 0 0 1 1h8M6 4.5h4',
  pin: 'M9.5 1.5l5 5-2 .5-2.5 2.5-.5 3-2-2-3.5 3.5M6.5 9.5l-2-2 3-.5L10 4.5l.5-2',
  eye_off: 'M2 2l12 12M6.6 6.6a2 2 0 0 0 2.8 2.8M4.2 4.3C2.6 5.4 1.5 8 1.5 8s2.4 4.5 6.5 4.5c1.3 0 2.4-.4 3.3-1M7 3.6c.3 0 .7-.1 1-.1 4.1 0 6.5 4.5 6.5 4.5s-.5 1-1.5 2.1',
  key: 'M10 6a2.5 2.5 0 1 1 0-.01M8.2 7.8 2.5 13.5M4 12l1.5 1.5M5.5 10.5 7 12',
}

defineProps({ name: { type: String, required: true }, size: { type: Number, default: 15 } })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" stroke="currentColor"
       stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path :d="PATHS[name]" />
  </svg>
</template>
