export type WebwrightErrorGuide = {
  category: string
  title: string
  summary: string
  actions: string[]
}

const guides: Record<string, Omit<WebwrightErrorGuide, 'category'>> = {
  api_key_missing: {
    title: 'API key missing',
    summary: 'Webwright could not authenticate with the configured LLM provider.',
    actions: [
      'Enter the provider API key in the LLM section above and click Check Key.',
      'Save LLM settings, then retry the selected TC.'
    ]
  },
  api_key_invalid: {
    title: 'API key rejected',
    summary: 'The stored provider credentials were rejected by the LLM API.',
    actions: [
      'Verify the provider, model name, and API key in Settings or the LLM panel.',
      'Reload available models, then retry the run.'
    ]
  },
  api_access_forbidden: {
    title: 'Provider access forbidden',
    summary: 'The LLM provider denied access for the configured account or model.',
    actions: [
      'Confirm the model is enabled for your account and billing is active.',
      'Switch to a supported model, then retry the run.'
    ]
  },
  bash_missing: {
    title: 'Shell runtime unavailable',
    summary: 'Webwright could not launch because the required shell/runtime was not found.',
    actions: [
      'Install Git Bash or configure the Worker runtime shell path in Settings.',
      'Run Settings validation, then retry the run.'
    ]
  },
  browser_missing: {
    title: 'Playwright browser missing',
    summary: 'The Playwright browser binaries required for Webwright generation are not installed.',
    actions: [
      'Install the bundled runtime or run Playwright browser install for the Worker environment.',
      'Open Settings and confirm runtime health before retrying.'
    ]
  },
  url_unreachable: {
    title: 'Start URL unreachable',
    summary: 'Webwright could not reach the configured start URL or target page.',
    actions: [
      'Verify the TC start URL, VPN/network access, and environment availability.',
      'Adjust the start URL or prompt context if login or redirects are required, then retry.'
    ]
  },
  timeout: {
    title: 'Webwright run timed out',
    summary: 'The Webwright process did not finish before the allowed time limit.',
    actions: [
      'Open Stderr/Stdout logs and inspect the run folder for the last recorded step.',
      'Retry with a narrower prompt or a more stable start URL.'
    ]
  },
  script_generation_failed: {
    title: 'Final script not generated',
    summary: 'Webwright finished without producing a usable final_script.py artifact.',
    actions: [
      'Review Stderr and the run folder for generation errors.',
      'Refine the prompt payload and retry the selected TC.'
    ]
  },
  webwright_not_found: {
    title: 'Webwright CLI unavailable',
    summary: 'The Worker could not find or execute the Webwright CLI/runtime package.',
    actions: [
      'Install or bundle the Webwright runtime from Settings.',
      'Run Settings validation and confirm live Webwright readiness before retrying.'
    ]
  },
  unknown: {
    title: 'Webwright run failed',
    summary: 'The Worker classified the failure but could not map it to a known recovery path.',
    actions: [
      'Open the run folder, Stderr, and Stdout logs for the raw failure details.',
      'Retry after fixing prompt, runtime, or network conditions.'
    ]
  }
}

export function describeWebwrightRunError(errorMessage?: string | null): WebwrightErrorGuide {
  const category = (errorMessage || 'unknown').trim().toLowerCase() || 'unknown'
  const guide = guides[category] || guides.unknown
  return { category, ...guide }
}

export function webwrightArtifactPath(outputPath: string, fileName: string) {
  const separator = outputPath.includes('\\') ? '\\' : '/'
  return `${outputPath.replace(/[\\/]+$/, '')}${separator}${fileName}`
}
