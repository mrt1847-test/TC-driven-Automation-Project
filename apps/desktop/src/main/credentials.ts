import { app, safeStorage } from 'electron'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'

type CredentialStore = Record<string, Record<string, string>>

function storePath(): string {
  const dir = join(app.getPath('userData'), 'credentials')
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true })
  }
  return join(dir, 'secrets.json')
}

function readStore(): CredentialStore {
  const path = storePath()
  if (!existsSync(path)) {
    return {}
  }
  try {
    return JSON.parse(readFileSync(path, 'utf-8')) as CredentialStore
  } catch {
    return {}
  }
}

function writeStore(store: CredentialStore): void {
  writeFileSync(storePath(), JSON.stringify(store, null, 2), 'utf-8')
}

async function setWithKeytar(service: string, account: string, password: string): Promise<void> {
  const keytar = await import('keytar')
  await keytar.setPassword(service, account, password)
}

async function getWithKeytar(service: string, account: string): Promise<string | null> {
  const keytar = await import('keytar')
  return keytar.getPassword(service, account)
}

function setWithSafeStorage(service: string, account: string, password: string): void {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error(
      'OS encryption is not available for Electron safeStorage. On Windows, sign in to a user profile with Credential Manager enabled.'
    )
  }
  const encrypted = safeStorage.encryptString(password).toString('base64')
  const store = readStore()
  if (!store[service]) {
    store[service] = {}
  }
  store[service][account] = encrypted
  writeStore(store)
}

function getWithSafeStorage(service: string, account: string): string | null {
  const store = readStore()
  const encrypted = store[service]?.[account]
  if (!encrypted) {
    return null
  }
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('OS encryption is not available; cannot decrypt stored API key.')
  }
  return safeStorage.decryptString(Buffer.from(encrypted, 'base64'))
}

export async function setCredential(
  service: string,
  account: string,
  password: string
): Promise<{ ok: true } | { ok: false; message: string }> {
  if (!password?.trim()) {
    return { ok: false, message: 'API key is empty.' }
  }
  if (!account?.trim()) {
    return { ok: false, message: 'Provider is not selected.' }
  }

  const errors: string[] = []

  try {
    await setWithKeytar(service, account, password)
    return { ok: true }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    errors.push(`Windows Credential Manager (keytar): ${message}`)
  }

  try {
    setWithSafeStorage(service, account, password)
    return { ok: true }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    errors.push(`Encrypted app store (safeStorage): ${message}`)
  }

  return {
    ok: false,
    message: errors.join(' ')
  }
}

export async function getCredential(
  service: string,
  account: string
): Promise<{ ok: true; password: string } | { ok: false; message: string }> {
  try {
    const fromKeytar = await getWithKeytar(service, account)
    if (fromKeytar) {
      return { ok: true, password: fromKeytar }
    }
  } catch {
    // fall through to safeStorage
  }

  try {
    const fromSafeStorage = getWithSafeStorage(service, account)
    if (fromSafeStorage) {
      return { ok: true, password: fromSafeStorage }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, message }
  }

  return { ok: false, message: `No API key stored for ${account}.` }
}
