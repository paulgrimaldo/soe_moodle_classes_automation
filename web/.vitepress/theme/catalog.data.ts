import { existsSync, readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../content')
const files = ['dcc', 'mia'].map(program => resolve(root, program, 'catalog.json'))

export default {
  watch: files,
  load() {
    return files.filter(path => existsSync(path)).map(path => JSON.parse(readFileSync(path, 'utf8')))
  },
}
