<script setup lang="ts">
import { computed, ref } from 'vue'
import { withBase } from 'vitepress'
import { data as catalogs } from './catalog.data'

const query = ref('')
const program = ref('TODOS')
const modules = catalogs.flatMap(catalog => catalog.modules.map(module => ({ ...module, program: catalog.program })))
const count = modules.reduce((total, module) => total + module.sessions.length, 0)
const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
const filtered = computed(() => modules.filter(module =>
  (program.value === 'TODOS' || module.program === program.value) &&
  normalize(`${module.title} ${module.number} ${module.program}`).includes(normalize(query.value))))
const title = (value: string) => value === value.toLocaleUpperCase('es')
  ? value[0] + value.slice(1).toLocaleLowerCase('es') : value
</script>

<template>
  <main class="library-home">
    <header class="library-intro">
      <div class="library-eyebrow"><span class="library-dot" /> ESPACIO DE ESTUDIO · DCC / MIA</div>
      <h1>El conocimiento,<br><em>sesión a sesión.</em></h1>
      <p>Tus apuntes en un solo lugar. Explora los módulos, conecta ideas y retoma donde lo dejaste.</p>
      <div class="library-stats" aria-label="Contenido disponible">
        <span><strong>{{ modules.length }}</strong> módulos</span>
        <span><strong>{{ count }}</strong> sesiones</span>
        <span>Diagramas · Fórmulas · Código</span>
      </div>
    </header>

    <section aria-label="Explorar módulos">
      <div class="library-toolbar">
        <div class="library-tabs" role="group" aria-label="Programa">
          <button v-for="item in ['TODOS', ...catalogs.map(c => c.program)]" :key="item"
            :aria-pressed="program === item" @click="program = item">{{ item === 'TODOS' ? 'Todos los módulos' : item }}</button>
        </div>
        <label class="library-filter"><span class="sr-only">Filtrar módulos</span>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
          <input v-model="query" type="search" placeholder="Filtrar módulos…">
        </label>
      </div>
      <div class="library-section-label">EXPLORAR LA BIBLIOTECA <span>{{ filtered.length }} módulos</span></div>
      <div class="library-grid">
        <a v-for="module in filtered" :key="module.id" :href="withBase(module.link)" class="module-card">
          <div class="module-card-top"><span>{{ module.program }}</span><span>MÓDULO {{ String(module.number).padStart(2, '0') }}</span></div>
          <h2>{{ title(module.title) }}</h2>
          <div class="module-card-bottom"><span>{{ module.sessions.length }} sesiones disponibles</span><span class="module-arrow" aria-hidden="true">↗</span></div>
        </a>
      </div>
      <p v-if="!filtered.length" class="library-empty">{{ modules.length ? 'No hay módulos que coincidan con tu búsqueda.' : 'La biblioteca está lista. Las sesiones aparecerán aquí cuando estén disponibles.' }}</p>
    </section>
  </main>
</template>
