// Collect Vitest's native cases through its runner API. Vitest's `list` output
// omits skipped tasks and empty modules, so it cannot describe a full suite.
import { createRequire } from 'node:module'
import { realpathSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

function fail(message) {
  process.stderr.write(`${message}\n`)
  process.exitCode = 2
}

async function main() {
  const [rootArg, ...rawArgs] = process.argv.slice(2)
  if (!rootArg || !path.isAbsolute(rootArg)) throw new Error('absolute checkout root is required')
  const root = path.resolve(rootArg)
  const requireFromRoot = createRequire(path.join(root, 'package.json'))
  const vitestEntry = requireFromRoot.resolve('vitest/node')
  const vitest = await import(pathToFileURL(vitestEntry).href)
  if (typeof vitest.parseCLI !== 'function' || typeof vitest.createVitest !== 'function') {
    throw new Error('installed Vitest does not expose the required native collection API')
  }
  const args = rawArgs[0] === 'run' ? rawArgs.slice(1) : rawArgs
  const parsed = vitest.parseCLI(['vitest', ...args])
  const ctx = await vitest.createVitest('test', { ...parsed.options, run: true, watch: false })
  if (!ctx || typeof ctx.collect !== 'function' || typeof ctx.close !== 'function') {
    throw new Error('installed Vitest runner has an unsupported collection API')
  }
  try {
    const collection = await ctx.collect(parsed.filter)
    const modules = collection?.testModules
    if (!Array.isArray(modules)) throw new Error('Vitest collection did not return a module array')
    if (!Array.isArray(collection.unhandledErrors) || collection.unhandledErrors.length) {
      throw new Error('Vitest native collection reported unhandled errors')
    }
    const merged = new Map()
    for (const module of modules) {
      if (typeof module.relativeModuleId !== 'string' || !module.relativeModuleId) {
        throw new Error('Vitest collection module lacks a relative module identity')
      }
      const filename = module.moduleId ?? module.task?.filepath
      if (typeof filename !== 'string' || !path.isAbsolute(filename)) throw new Error('Vitest module lacks an absolute source path')
      const unit = path.relative(root, realpathSync(filename)).split(path.sep).join('/')
      if (!unit || unit === '..' || unit.startsWith('../') || path.isAbsolute(unit)) throw new Error('Vitest module is outside the checkout')
      if (unit.startsWith('/') || unit.split('/').some(part => part === '..' || part === '.')) {
        throw new Error('Vitest collection produced a non-normalized module identity')
      }
      const projectName = module.project?.name ?? ''
      if (typeof projectName !== 'string' || typeof module.children?.allTests !== 'function') {
        throw new Error('Vitest collection module has an unsupported task tree')
      }
      const current = merged.get(unit) ?? { cases: [], case_modes: {}, skipped: false }
      const tests = Array.from(module.children.allTests())
      for (const test of tests) {
        if (typeof test.id !== 'string' || !test.id || typeof test.options?.mode !== 'string') {
          throw new Error('Vitest collected case lacks a native ID or mode')
        }
        const mode = test.options.mode
        if (!['run', 'only', 'skip', 'todo'].includes(mode)) {
          throw new Error(`Vitest collected unsupported case mode: ${mode}`)
        }
        const id = JSON.stringify([projectName, unit, test.id])
        if (Object.hasOwn(current.case_modes, id)) throw new Error('Vitest produced a duplicate canonical case ID')
        current.cases.push(id)
        current.case_modes[id] = mode
      }
      current.skipped ||= tests.length === 0 || module.state?.() === 'skip'
      merged.set(unit, current)
    }
    const result = Object.fromEntries([...merged.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([unit, entry]) => {
      entry.cases.sort()
      return [unit, entry]
    }))
    process.stdout.write(`${JSON.stringify(result)}\n`)
  } finally {
    await ctx.close()
  }
}

main().catch(error => fail(`Vitest native collection failed: ${error?.stack ?? error}`))
