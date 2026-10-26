import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve, dirname } from 'node:path'
import { defineConfig } from 'vitepress'

const content = resolve(dirname(fileURLToPath(import.meta.url)), '../../content')
const catalogs = ['dcc', 'mia'].flatMap(program => {
  const path = resolve(content, program, 'catalog.json')
  return existsSync(path) ? [JSON.parse(readFileSync(path, 'utf8'))] : []
})
const base = process.env.WEB_BASE || '/'
if (!base.startsWith('/') || !base.endsWith('/')) {
  throw new Error('WEB_BASE debe empezar y terminar con /')
}

export default defineConfig({
  srcDir: '../content',
  srcExclude: ['public/**'],
  base,
  lang: 'es',
  title: 'Biblioteca académica',
  description: 'Apuntes de DCC y MIA, organizados por módulo y sesión.',
  head: [['meta', { name: 'theme-color', content: '#f7f8f4' }]],
  lastUpdated: false,
  themeConfig: {
    siteTitle: 'Biblioteca académica',
    logo: '/library.svg',
    nav: [{ text: 'Biblioteca', link: '/' }, ...catalogs.map(catalog => ({
      text: catalog.program, link: `/${catalog.program.toLowerCase()}/`,
    }))],
    sidebar: Object.fromEntries(catalogs.flatMap(catalog => catalog.modules.map(module => [module.link, [
      { text: `${catalog.program} · Módulo ${module.number}`, link: module.link },
      ...(module.contexts?.length ? [{ text: 'Contexto de las semanas', collapsed: true,
        items: module.contexts.map(context => ({ text: `Semana ${context.week}`, link: context.link })) }] : []),
      { text: module.title, items: module.sessions.map(session => ({
        text: `${session.label} · ${session.title}`, link: session.link,
      })) },
    ]]))),
    outline: { level: [2, 3], label: 'En esta sesión' },
    docFooter: { prev: 'Sesión anterior', next: 'Siguiente sesión' },
    returnToTopLabel: 'Volver arriba',
    sidebarMenuLabel: 'Sesiones',
    darkModeSwitchLabel: 'Apariencia',
    lightModeSwitchTitle: 'Usar tema claro',
    darkModeSwitchTitle: 'Usar tema oscuro',
    notFound: { title: 'Página no encontrada', quote: 'Busca el apunte en la biblioteca.',
      linkLabel: 'Volver a la biblioteca', linkText: 'Volver a la biblioteca' },
    search: { provider: 'local', options: { locales: { root: { translations: {
      button: { buttonText: 'Buscar apuntes', buttonAriaLabel: 'Buscar en la biblioteca' },
      modal: { displayDetails: 'Mostrar detalles', resetButtonTitle: 'Limpiar búsqueda',
        backButtonTitle: 'Cerrar búsqueda', noResultsText: 'No se encontraron resultados',
        footer: { selectText: 'seleccionar', navigateText: 'navegar', closeText: 'cerrar' } },
    } } } } },
    footer: { message: 'DCC / MIA · Biblioteca de apuntes académicos' },
  },
  markdown: {
    math: true,
    // Academic punctuation must remain literal, including combinations such as :*.
    emoji: { shortcuts: {} },
    config(md) {
      const fence = md.renderer.rules.fence!
      md.renderer.rules.fence = (tokens, index, options, env, renderer) => {
        if (tokens[index].info.trim() !== 'mermaid') return fence(tokens, index, options, env, renderer)
        return `<MermaidDiagram source="${md.utils.escapeHtml(tokens[index].content)}" />\n`
      }
    },
  },
})
