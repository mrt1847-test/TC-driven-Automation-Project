type ProviderModelPayload = {
  data?: Array<{ id?: string }>
  error?: { message?: string }
}

export type ProviderModelsResult =
  | { ok: true; provider: string; models: string[] }
  | { ok: false; provider: string; message: string }

function modelId(item: { id?: string }): string {
  return typeof item.id === 'string' ? item.id.trim() : ''
}

function sortModels(models: string[]): string[] {
  return [...new Set(models)].sort((left, right) =>
    left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
  )
}

function isOpenAITextModel(id: string): boolean {
  return /^(gpt-|o[1-9](?:-|$))/.test(id)
    && !/(?:image|audio|realtime|transcribe|tts|search-preview)/.test(id)
}

async function parseResponse(response: Response): Promise<ProviderModelPayload> {
  try {
    return await response.json() as ProviderModelPayload
  } catch {
    return {}
  }
}

function responseError(response: Response, payload: ProviderModelPayload): string {
  return payload.error?.message || `Provider model request failed with HTTP ${response.status}.`
}

async function listOpenAIModels(apiKey: string): Promise<string[]> {
  const response = await fetch('https://api.openai.com/v1/models', {
    headers: { Authorization: `Bearer ${apiKey}` },
    signal: AbortSignal.timeout(15_000)
  })
  const payload = await parseResponse(response)
  if (!response.ok) throw new Error(responseError(response, payload))
  return sortModels((payload.data || []).map(modelId).filter((id) => id && isOpenAITextModel(id)))
}

async function listAnthropicModels(apiKey: string): Promise<string[]> {
  const response = await fetch('https://api.anthropic.com/v1/models?limit=1000', {
    headers: {
      'anthropic-version': '2023-06-01',
      'x-api-key': apiKey
    },
    signal: AbortSignal.timeout(15_000)
  })
  const payload = await parseResponse(response)
  if (!response.ok) throw new Error(responseError(response, payload))
  return sortModels((payload.data || []).map(modelId).filter(Boolean))
}

export async function listProviderModels(provider: string, apiKey: string): Promise<ProviderModelsResult> {
  try {
    const models = provider === 'openai'
      ? await listOpenAIModels(apiKey)
      : provider === 'anthropic'
        ? await listAnthropicModels(apiKey)
        : null

    if (models === null) {
      return {
        ok: false,
        provider,
        message: 'Azure OpenAI model listing requires an Azure endpoint and deployment configuration.'
      }
    }
    if (!models.length) {
      return { ok: false, provider, message: 'No compatible text-generation models are available for this key.' }
    }
    return { ok: true, provider, models }
  } catch (error) {
    return {
      ok: false,
      provider,
      message: error instanceof Error ? error.message : 'Provider model request failed.'
    }
  }
}
