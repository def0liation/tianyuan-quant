import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const postcss = require('postcss')
const tailwindcss = require('tailwindcss')
const autoprefixer = require('autoprefixer')
const tailwindGeneratedSourcePath = require.resolve('tailwindcss/package.json')
const fallbackSourceInput = postcss.parse('', { from: tailwindGeneratedSourcePath }).source.input

function tailwindGeneratedSourcePlugin() {
  return {
    postcssPlugin: 'super-tailwind-generated-source',
    Once(root) {
      const sourceInput = root.source?.input ?? fallbackSourceInput

      root.walkDecls((declaration) => {
        if (declaration.source?.input?.file) {
          return
        }

        declaration.source = {
          input: sourceInput,
          start: declaration.source?.start ?? { line: 1, column: 1 },
          end: declaration.source?.end ?? { line: 1, column: 1 },
        }
      })
    },
  }
}

export default {
  plugins: [tailwindcss(), autoprefixer(), tailwindGeneratedSourcePlugin()],
}
