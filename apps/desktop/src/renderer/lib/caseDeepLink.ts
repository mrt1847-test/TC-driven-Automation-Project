import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { api, type TestCase } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

const AUTOMATION_KEY_PARAMS = ['automation_key', 'automationKey', 'case', 'caseKey']

export function getAutomationKeyFromSearch(search: string) {
  const params = new URLSearchParams(search.startsWith('?') ? search : `?${search}`)
  for (const name of AUTOMATION_KEY_PARAMS) {
    const value = params.get(name)?.trim()
    if (value) return value
  }
  return ''
}

export function caseDeepLink(path: string, automationKey?: string | null) {
  const key = automationKey?.trim()
  if (!key) return path

  const [pathAndSearch, hash] = path.split('#', 2)
  const [pathname, search = ''] = pathAndSearch.split('?', 2)
  const params = new URLSearchParams(search)
  params.set('automation_key', key)

  const query = params.toString()
  return `${pathname}${query ? `?${query}` : ''}${hash ? `#${hash}` : ''}`
}

export function findCaseByAutomationKey(cases: TestCase[], automationKey: string, projectId?: string) {
  const key = automationKey.trim()
  if (!key) return undefined
  return cases.find((item) => (
    item.automation_key === key && (!projectId || item.project_id === projectId)
  ))
}

export function useAutomationKeyDeepLink(providedCases?: TestCase[]) {
  const location = useLocation()
  const project = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const setSelectedCase = useAppStore((s) => s.setSelectedCase)
  const requestedAutomationKey = useMemo(
    () => getAutomationKeyFromSearch(location.search),
    [location.search]
  )
  const shouldFetchCases = Boolean(project?.id && requestedAutomationKey && !providedCases)

  const casesQuery = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: shouldFetchCases
  })

  const cases = providedCases ?? casesQuery.data ?? []
  const resolvedCase = useMemo(
    () => findCaseByAutomationKey(cases, requestedAutomationKey, project?.id),
    [cases, project?.id, requestedAutomationKey]
  )

  useEffect(() => {
    if (!project?.id || !requestedAutomationKey || !resolvedCase) return
    if (selectedCase?.id === resolvedCase.id && selectedCase.project_id === project.id) return
    setSelectedCase(resolvedCase)
  }, [project?.id, requestedAutomationKey, resolvedCase, selectedCase?.id, selectedCase?.project_id, setSelectedCase])

  return {
    isResolving: Boolean(requestedAutomationKey && project?.id && shouldFetchCases && casesQuery.isFetching),
    notFound: Boolean(requestedAutomationKey && project?.id && !casesQuery.isFetching && cases.length > 0 && !resolvedCase),
    requestedAutomationKey,
    resolvedCase
  }
}
