// Vitest reporter that proves terminal outcomes for the expected native cases.
import fs from 'node:fs'
import path from 'node:path'

const observationPath = process.env.CI_FLEET_VITEST_CASE_OBSERVATION_PATH
const expectedPath = process.env.CI_FLEET_VITEST_CASE_EXPECTED_PATH
const sourceRoot = fs.realpathSync(process.env.CI_FLEET_VITEST_CASE_ROOT ?? process.cwd())

function canonical(module, test) {
  const filename = module.moduleId ?? module.task?.filepath
  if (typeof filename !== 'string' || !path.isAbsolute(filename)) throw new Error('Vitest case lacks an absolute source path')
  const unit = path.relative(sourceRoot, fs.realpathSync(filename)).split(path.sep).join('/')
  if (!unit || unit === '..' || unit.startsWith('../') || path.isAbsolute(unit)) throw new Error('Vitest case is outside the checkout')
  return JSON.stringify([module.project?.name ?? '', unit, test.id])
}

export default class VitestCaseReporter {
  constructor() {
    this.observed = new Map()
    this.error = null
  }

  onTestCaseResult(test) {
    try {
      const module = test.module
      if (!module || typeof module.relativeModuleId !== 'string') throw new Error('Vitest reporter received an unsupported case module')
      const id = canonical(module, test)
      const mode = test.options?.mode
      const result = test.result?.()
      let outcome
      if (result?.state === 'skipped' || mode === 'skip' || mode === 'todo') outcome = 'skipped'
      else if (result?.state === 'passed' && (test.task?.fails === true || test.options?.fails === true)) outcome = 'expected-failure'
      else if (result?.state === 'passed') outcome = 'passed'
      else throw new Error(`Vitest case ${id} did not reach a successful terminal state`)
      if (this.observed.has(id)) throw new Error(`Vitest reported duplicate case ID ${id}`)
      this.observed.set(id, { mode, outcome })
    } catch (error) {
      this.error = error
    }
  }

  onTestRunEnd(modules, unhandledErrors, reason) {
    try {
      if (reason !== 'passed' || !Array.isArray(unhandledErrors) || unhandledErrors.length !== 0) {
        throw new Error('Vitest run did not finish without unhandled errors')
      }
      if (this.error) throw this.error
      if (!observationPath || !expectedPath) throw new Error('case reporter output paths are not configured')
      const expected = JSON.parse(fs.readFileSync(expectedPath, 'utf8'))
      const expectedModes = expected.case_modes
      const expectedIds = Object.keys(expectedModes).sort()
      const observedIds = [...this.observed.keys()].sort()
      if (JSON.stringify(observedIds) !== JSON.stringify(expectedIds)) {
        throw new Error('Vitest terminal case IDs differ from the assigned native cases')
      }
      const outcomes = {}
      let executable = 0
      for (const id of expectedIds) {
        const actual = this.observed.get(id)
        if (actual.mode !== expectedModes[id]) throw new Error(`Vitest case mode changed during execution: ${id}`)
        if (expectedModes[id] === 'run' || expectedModes[id] === 'only') {
          if (actual.outcome !== 'passed' && actual.outcome !== 'expected-failure') {
            throw new Error(`selected Vitest case did not pass: ${id}`)
          }
          executable += 1
        }
        outcomes[id] = actual.outcome
      }
      if (executable === 0) throw new Error('Vitest shard completed no passing or expected-failure cases')
      fs.mkdirSync(path.dirname(observationPath), { recursive: true })
      fs.writeFileSync(observationPath, `${JSON.stringify({ case_results: outcomes })}\n`, { flag: 'wx' })
    } catch (error) {
      process.stderr.write(`Vitest case reporter refused receipt evidence: ${error?.stack ?? error}\n`)
      process.exitCode = 2
    }
  }
}
