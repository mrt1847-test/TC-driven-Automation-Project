import { create } from 'zustand'
import type { Project, TestCase } from '@/lib/api'

const LOG_BUFFER_LIMIT = 500
const SETUP_COMPLETE_KEY = 'setupComplete'
const CURRENT_PROJECT_KEY = 'currentProject'
const SELECTED_CASE_KEY = 'selectedCase'

type SelectedCase = Pick<TestCase, 'id' | 'project_id' | 'title' | 'automation_key' | 'status'>

export interface AppState {
  setupComplete: boolean
  setupWizardRerunOpen: boolean
  currentProject: Project | null
  selectedCase: SelectedCase | null
  logs: string[]
  setSetupComplete: (v: boolean) => void
  openSetupWizardRerun: () => void
  closeSetupWizardRerun: () => void
  setCurrentProject: (p: Project | null) => void
  setSelectedCase: (c: TestCase | SelectedCase | null) => void
  appendLog: (line: string) => void
  clearLogs: () => void
}

function readCurrentProject(): Project | null {
  const stored = localStorage.getItem(CURRENT_PROJECT_KEY)
  if (!stored) return null

  try {
    return JSON.parse(stored) as Project
  } catch {
    localStorage.removeItem(CURRENT_PROJECT_KEY)
    return null
  }
}

function readSelectedCase(): SelectedCase | null {
  const stored = localStorage.getItem(SELECTED_CASE_KEY)
  if (!stored) return null

  try {
    return JSON.parse(stored) as SelectedCase
  } catch {
    localStorage.removeItem(SELECTED_CASE_KEY)
    return null
  }
}

export const useAppStore = create<AppState>((set) => ({
  setupComplete: localStorage.getItem(SETUP_COMPLETE_KEY) === 'true',
  setupWizardRerunOpen: false,
  currentProject: readCurrentProject(),
  selectedCase: readSelectedCase(),
  logs: [],
  setSetupComplete: (v) => {
    localStorage.setItem(SETUP_COMPLETE_KEY, String(v))
    set({ setupComplete: v })
  },
  openSetupWizardRerun: () => set({ setupWizardRerunOpen: true }),
  closeSetupWizardRerun: () => set({ setupWizardRerunOpen: false }),
  setCurrentProject: (p) => {
    if (p) {
      localStorage.setItem(CURRENT_PROJECT_KEY, JSON.stringify(p))
    } else {
      localStorage.removeItem(CURRENT_PROJECT_KEY)
    }
    set((state) => {
      const selectedCase = p && state.selectedCase?.project_id === p.id ? state.selectedCase : null
      if (!selectedCase) {
        localStorage.removeItem(SELECTED_CASE_KEY)
      }
      return { currentProject: p, selectedCase }
    })
  },
  setSelectedCase: (c) => {
    if (c) {
      const selected = {
        id: c.id,
        project_id: c.project_id,
        title: c.title,
        automation_key: c.automation_key,
        status: c.status
      }
      localStorage.setItem(SELECTED_CASE_KEY, JSON.stringify(selected))
      set({ selectedCase: selected })
    } else {
      localStorage.removeItem(SELECTED_CASE_KEY)
      set({ selectedCase: null })
    }
  },
  appendLog: (line) => set((s) => ({ logs: [...s.logs.slice(-(LOG_BUFFER_LIMIT - 1)), line] })),
  clearLogs: () => set({ logs: [] })
}))
