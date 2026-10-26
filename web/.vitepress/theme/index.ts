import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import LibraryHome from './LibraryHome.vue'
import MermaidDiagram from './MermaidDiagram.vue'
import NoteHeader from './NoteHeader.vue'
import { h } from 'vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, { 'doc-before': () => h(NoteHeader) }),
  enhanceApp({ app }) {
    app.component('LibraryHome', LibraryHome)
    app.component('MermaidDiagram', MermaidDiagram)
  },
} satisfies Theme
