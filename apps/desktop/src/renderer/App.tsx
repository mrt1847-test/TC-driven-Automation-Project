import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAppStore } from '@/store/appStore'
import { Layout } from '@/components/Layout'
import { SetupWizard } from '@/pages/SetupWizard'
import { DashboardPage } from '@/pages/DashboardPage'
import { ImportPage } from '@/pages/ImportPage'
import { CasesPage } from '@/pages/CasesPage'
import { WebwrightPage } from '@/pages/WebwrightPage'
import { MappingPage } from '@/pages/MappingPage'
import { IdePage } from '@/pages/IdePage'
import { RunnerPage } from '@/pages/RunnerPage'
import { ResultsPage } from '@/pages/ResultsPage'
import { ExportPage } from '@/pages/ExportPage'
import { SettingsPage } from '@/pages/SettingsPage'

const qc = new QueryClient()

export function App() {
  const setupComplete = useAppStore((s) => s.setupComplete)
  const setupWizardRerunOpen = useAppStore((s) => s.setupWizardRerunOpen)

  if (!setupComplete) {
    return (
      <QueryClientProvider client={qc}>
        <SetupWizard mode="first-run" />
      </QueryClientProvider>
    )
  }

  if (setupWizardRerunOpen) {
    return (
      <QueryClientProvider client={qc}>
        <SetupWizard mode="rerun" />
      </QueryClientProvider>
    )
  }

  return (
    <QueryClientProvider client={qc}>
      <HashRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="import" element={<ImportPage />} />
            <Route path="cases" element={<CasesPage />} />
            <Route path="webwright" element={<WebwrightPage />} />
            <Route path="mapping" element={<MappingPage />} />
            <Route path="ide" element={<IdePage />} />
            <Route path="runner" element={<RunnerPage />} />
            <Route path="results" element={<ResultsPage />} />
            <Route path="export" element={<ExportPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </HashRouter>
    </QueryClientProvider>
  )
}
