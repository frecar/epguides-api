import { openSync, realpathSync, writeFileSync, closeSync } from 'node:fs'
import path from 'node:path'

function fileUnit(module, root) {
  if (typeof module.relativeModuleId !== 'string' || !module.relativeModuleId) {
    throw new Error('Vitest module has no relativeModuleId')
  }
  const candidate = path.resolve(root, module.relativeModuleId)
  const actual = realpathSync(candidate)
  const relative = path.relative(root, actual).split(path.sep).join('/')
  if (!relative || relative === '.' || relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) {
    throw new Error('Vitest module is outside the checkout')
  }
  return relative
}

export default class CiShardReporter {
  constructor() {
    this.root = realpathSync(process.cwd())
    this.collected = []
  }

  onTestModuleCollected(module) {
    this.collected.push(fileUnit(module, this.root))
  }

  onTestRunEnd(modules, unhandledErrors, reason) {
    if (reason !== 'passed' || unhandledErrors.length !== 0) return
    if (!Array.isArray(modules) || modules.length === 0) {
      throw new Error('Vitest completed without module collection evidence')
    }

    const completed = []
    for (const module of modules) {
      const state = module.state()
      if (state !== 'passed' && state !== 'skipped') {
        throw new Error(`Vitest module did not complete successfully: ${state}`)
      }
      for (const test of module.children.allTests()) {
        const testState = test.result().state
        if (testState !== 'passed' && testState !== 'skipped') {
          throw new Error(`Vitest test did not complete successfully: ${testState}`)
        }
      }
      completed.push(fileUnit(module, this.root))
    }

    const ordered = [...completed].sort()
    const collected = [...this.collected].sort()
    if (new Set(ordered).size !== ordered.length || JSON.stringify(ordered) !== JSON.stringify(collected)) {
      throw new Error('Vitest collected and completed module lists differ')
    }

    const output = process.env.CI_FLEET_VITEST_OBSERVATION_PATH
    if (!output) throw new Error('CI_FLEET_VITEST_OBSERVATION_PATH is required')
    const fd = openSync(output, 'wx', 0o600)
    try {
      writeFileSync(fd, `${JSON.stringify(ordered)}\n`, 'utf8')
    } finally {
      closeSync(fd)
    }
  }
}
