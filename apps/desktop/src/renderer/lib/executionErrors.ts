export type ExecutionBootstrap = {
  ok?: boolean
  allOk?: boolean
  message?: string
  checks?: Record<string, boolean>
  pipError?: string
  playwrightError?: string
  playwrightBrowser?: { ok?: boolean; message?: string }
}

export type ExecutionErrorGuide = {
  category: string
  title: string
  summary: string
  actions: string[]
  isBootstrapFailure: boolean
}

const guides: Record<string, Omit<ExecutionErrorGuide, 'category' | 'isBootstrapFailure'>> = {
  runtime_files_missing: {
    title: 'Generated runtime files missing',
    summary: 'The generated project is missing files required before runner execution can start.',
    actions: [
      'Run Generate Project or regenerate the affected TC from Automation IDE.',
      'Confirm mappings/cases.yaml, runner/cli.py, and requirements.txt exist in the generated tree.'
    ]
  },
  pip_install_failed: {
    title: 'Python dependencies not installed',
    summary: 'Bootstrap could not install the generated project requirements.',
    actions: [
      'Click Install Dependencies in the Runner panel, then review stderr in the terminal.',
      'Verify the Worker Python runtime in Settings, then retry the run.'
    ]
  },
  playwright_install_failed: {
    title: 'Playwright install failed',
    summary: 'Bootstrap could not install the Playwright browser package for the selected browser.',
    actions: [
      'Click Install Dependencies to rerun pip and Playwright install.',
      'Open Settings, confirm runtime health, then retry with the same browser.'
    ]
  },
  browser_missing: {
    title: 'Playwright browser missing',
    summary: 'Dependencies installed, but the selected browser executable is not available.',
    actions: [
      'Click Install Dependencies to reinstall the browser binary.',
      'Retry after confirming the browser choice matches the generated project runtime.'
    ]
  },
  config_env_missing: {
    title: 'Config or environment missing',
    summary: 'Runner bootstrap or execution could not find required config or env values.',
    actions: [
      'Review generated config/env files and project environment settings.',
      'Add the missing env override locally without committing secrets, then rerun.'
    ]
  },
  test_failed: {
    title: 'Test execution failed',
    summary: 'Runner finished, but one or more generated test cases failed.',
    actions: [
      'Open the Diagnosis panel for disposition guidance and rerun-failed.',
      'Inspect screenshot/trace artifacts and generated source for the failing automation key.'
    ]
  },
  runner_cli_error: {
    title: 'Runner CLI error',
    summary: 'The generated runner exited before producing a usable results summary.',
    actions: [
      'Open stderr/stdout in the terminal and the run folder for the raw CLI failure.',
      'Fix generated runner inputs or runtime config, then retry the run.'
    ]
  },
  bootstrap_failed: {
    title: 'Runtime bootstrap failed',
    summary: 'Execution stopped before runner.cli because generated runtime bootstrap did not pass.',
    actions: [
      'Run Health Check, then Install Dependencies from the Runner panel.',
      'Retry after bootstrap reports ready.'
    ]
  },
  unknown: {
    title: 'Execution failed',
    summary: 'The Worker recorded a failed execution without a known recovery category.',
    actions: [
      'Open the run folder, stderr log, and terminal output for the raw failure.',
      'Use Health Check and Install Dependencies before retrying.'
    ]
  }
}

function classifyBootstrapMessage(message: string): string {
  const normalized = message.trim().toLowerCase()
  if (!normalized) return 'bootstrap_failed'
  if (
    normalized.includes('requirements.txt missing') ||
    normalized.includes('runner/cli.py missing') ||
    normalized.includes('mappings/cases.yaml missing') ||
    normalized.includes('runtime files are incomplete')
  ) {
    return 'runtime_files_missing'
  }
  if (normalized.includes('pip install failed')) return 'pip_install_failed'
  if (normalized.includes('playwright install failed')) return 'playwright_install_failed'
  if (
    normalized.includes('browser executable') ||
    normalized.includes('executable missing') ||
    normalized.includes('playwright import failed')
  ) {
    return 'browser_missing'
  }
  if (normalized.includes('config') || normalized.includes('.env') || normalized.includes('environment')) {
    return 'config_env_missing'
  }
  return 'bootstrap_failed'
}

function classifyResultError(error: string): string {
  const normalized = error.trim().toLowerCase()
  if (!normalized) return 'unknown'
  if (normalized.includes('requirements.txt missing') || normalized.includes('runner/cli.py missing')) {
    return 'runtime_files_missing'
  }
  if (normalized.includes('pip install failed') || normalized.includes('pip failed')) return 'pip_install_failed'
  if (normalized.includes('playwright install failed')) return 'playwright_install_failed'
  if (normalized.includes('browser') && (normalized.includes('missing') || normalized.includes('executable'))) {
    return 'browser_missing'
  }
  if (normalized.includes('config') || normalized.includes('.env') || normalized.includes('environment variable')) {
    return 'config_env_missing'
  }
  if (normalized.includes('runner.cli') || normalized.includes('no such file') || normalized.includes('modulenotfounderror')) {
    return 'runner_cli_error'
  }
  return 'test_failed'
}

export function describeExecutionError(input: {
  bootstrap?: ExecutionBootstrap | null
  runStatus?: string
  primaryError?: string | null
  failedCount?: number
}): ExecutionErrorGuide | null {
  if (input.runStatus !== 'failed') return null

  const bootstrap = input.bootstrap
  if (bootstrap && bootstrap.ok === false) {
    const category = classifyBootstrapMessage(bootstrap.message || '')
    const guide = guides[category] || guides.bootstrap_failed
    return { category, ...guide, isBootstrapFailure: true }
  }

  const failedCount = input.failedCount ?? 0
  const category = input.primaryError ? classifyResultError(input.primaryError) : failedCount > 0 ? 'test_failed' : 'runner_cli_error'
  const guide = guides[category] || guides.unknown
  return { category, ...guide, isBootstrapFailure: false }
}

export function executionRunDir(resultPath?: string | null) {
  if (!resultPath) return ''
  const separator = resultPath.includes('\\') ? '\\' : '/'
  const parts = resultPath.replace(/[\\/]+$/, '').split(separator)
  parts.pop()
  return parts.join(separator)
}

export function executionArtifactPath(resultPath: string | undefined | null, fileName: string) {
  const runDir = executionRunDir(resultPath)
  if (!runDir) return ''
  const separator = runDir.includes('\\') ? '\\' : '/'
  return `${runDir}${separator}${fileName}`
}
