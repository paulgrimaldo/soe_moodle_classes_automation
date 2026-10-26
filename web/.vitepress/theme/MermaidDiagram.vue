<script setup lang="ts">
import { onMounted, ref, watch, useId } from 'vue'
import { useData } from 'vitepress'

const props = defineProps<{ source: string }>()
const { isDark } = useData()
const svg = ref('')
const error = ref(false)
const expanded = ref(false)
const id = `diagram-${useId().replace(/[^a-zA-Z0-9-]/g, '')}`
let revision = 0
let mounted = false

async function render() {
  if (!mounted) return
  const current = ++revision
  try {
    const { default: mermaid } = await import('mermaid')
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict',
      theme: isDark.value ? 'dark' : 'neutral', suppressErrorRendering: true })
    const result = await mermaid.render(`${id}-${current}`, props.source)
    if (current === revision) { svg.value = result.svg; error.value = false }
  } catch {
    if (current === revision) { error.value = true; svg.value = '' }
  }
}
onMounted(() => { mounted = true; render() })
watch([() => props.source, isDark], render)
</script>

<template>
  <figure class="academic-diagram" :class="{ expanded }">
    <figcaption><span>DIAGRAMA</span><button v-if="!error" :aria-pressed="expanded" @click="expanded = !expanded">{{ expanded ? 'Reducir' : 'Ampliar' }}</button></figcaption>
    <div v-if="svg" class="diagram-canvas" v-html="svg" />
    <p v-else-if="!error" class="diagram-loading" role="status">Cargando diagrama…</p>
    <p v-if="error" role="status">No se pudo dibujar este diagrama. Puedes consultar su código.</p>
    <details :open="error"><summary>Ver código Mermaid</summary><pre><code>{{ source }}</code></pre></details>
  </figure>
</template>
