import { create } from 'zustand'
import type { Project } from '@/lib/api'

interface AppState {
  setupComplete: boolean
  currentProject: Project | null
  logs: string[]
  setSetupComplete: (v: boolean) => void
  setCurrentProject: (p: Project | null) => void
  appendLog: (line: string) => void
  clearLogs: () => void
}

export const useAppStore = create<AppState>((set) => ({
  setupComplete: localStorage.getItem('setupComplete') === 'true',
  currentProject: null,
  logs: [],
  setSetupComplete: (v) => {
    localStorage.setItem('setupComplete', String(v))
    set({ setupComplete: v })
  },
  setCurrentProject: (p) => set({ currentProject: p }),
  appendLog: (line) => set((s) => ({ logs: [...s.logs.slice(-500), line] })),
  clearLogs: () => set({ logs: [] })
}))
