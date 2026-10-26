<script setup lang="ts">
import { useData, withBase } from 'vitepress'
const { frontmatter } = useData()
const date = (value: string) => new Intl.DateTimeFormat('es', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`))
</script>

<template>
  <div v-if="frontmatter.academic" class="note-header">
    <a :href="withBase(`/${frontmatter.program.toLowerCase()}/`)">{{ frontmatter.program }}</a>
    <span aria-hidden="true">/</span><span>Módulo {{ frontmatter.module_number }}</span>
    <span aria-hidden="true">/</span><span>{{ frontmatter.label }}</span>
    <div class="note-tools">
      <span>{{ frontmatter.date ? date(frontmatter.date) : 'Fecha de clase no disponible' }} · Revisión {{ frontmatter.revision }}<template v-if="frontmatter.source === 'notion'"> · Fuente: Notion</template></span>
      <a v-if="frontmatter.week_context" :href="withBase(frontmatter.week_context)">Contexto de la semana</a>
      <a :href="withBase(frontmatter.download)" download>Descargar Markdown <span aria-hidden="true">↓</span></a>
    </div>
  </div>
</template>
