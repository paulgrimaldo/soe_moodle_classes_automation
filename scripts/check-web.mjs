import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { createMarkdownRenderer } from 'vitepress'
import { JSDOM } from 'jsdom'

const root = resolve(process.argv[2] || 'content')
const hash = value => createHash('sha256').update(value).digest('hex')
const md = await createMarkdownRenderer(process.cwd(), { html: false })
// Mermaid's parser sanitizes diagram labels using the DOM, even without rendering.
const { window } = new JSDOM('')
globalThis.window = window
globalThis.document = window.document
const { default: mermaid } = await import('mermaid')
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true })
let sessions = 0
let diagrams = 0
const failures = []

for (const program of ['dcc', 'mia']) {
  const file = resolve(root, program, 'catalog.json')
  if (!existsSync(file)) continue
  const catalog = JSON.parse(readFileSync(file, 'utf8'))
  const manifest = JSON.parse(readFileSync(resolve(root, `.export-${program}.json`), 'utf8'))
  for (const [relative, expected] of Object.entries(manifest.files)) {
    const path = resolve(root, relative)
    if (!path.startsWith(`${root}/`) || !existsSync(path) || hash(readFileSync(path)) !== expected) {
      failures.push(`${relative}: archivo ausente o modificado desde la exportación`)
    }
  }
  for (const module of catalog.modules) {
    for (const session of [...module.sessions, ...(module.contexts || [])]) {
      if ('session_id' in session) sessions++
      const path = resolve(root, session.link.slice(1).replace(/\.html$/, '.md'))
      const download = resolve(root, 'public', session.download.slice(1))
      if (!existsSync(download) || hash(readFileSync(download)) !== session.content_hash) {
        failures.push(`${session.link}: descarga distinta de la revisión exportada`)
      }
      const source = readFileSync(path, 'utf8').replace(/^---\n[\s\S]*?\n---\n/, '')
      for (const token of md.parse(source, {})) {
        if (token.type !== 'fence' || token.info.trim() !== 'mermaid') continue
        diagrams++
        try {
          await mermaid.parse(token.content)
        } catch (error) {
          failures.push(`${session.link}: Mermaid (línea ${token.map[0] + 1}): ${error.message.split('\n')[0]}`)
        }
      }
    }
  }
}
if (failures.length) {
  console.error(failures.join('\n'))
  process.exitCode = 1
} else {
  console.log(`Biblioteca verificada: ${sessions} sesiones, ${diagrams} diagramas Mermaid.`)
}
