import type { GenerationConflictDetail } from '@/lib/api'
import { getGenerationConflictDetail } from '@/lib/api'
import type { MaintenanceImpactSummary } from '@/components/MaintenanceImpactReview'

export function buildGenerationConflictSummary(
  error: unknown,
  actionLabel: string,
): MaintenanceImpactSummary | null {
  const detail = getGenerationConflictDetail(error)
  if (!detail) return null
  const summary = maintenanceSummaryFromGenerationConflict(detail, actionLabel)
  summary.guidance = generationConflictGuidance(summary)
  return summary
}

export function maintenanceSummaryFromGenerationConflict(
  detail: GenerationConflictDetail,
  actionLabel: string,
): MaintenanceImpactSummary {
  const editedFiles = detail.editedFiles || []
  const staleFiles = detail.staleFiles || []
  const conflictFiles = detail.conflictFiles || []
  const hasConflict = Boolean(conflictFiles.length || editedFiles.length)

  return {
    actionLabel,
    status: hasConflict ? 'conflict' : 'preview',
    affectedFiles: detail.affectedFiles || [],
    changedFiles: detail.changedFiles,
    preservedFiles: detail.preservedFiles || [],
    editedFiles,
    staleFiles,
    conflictFiles,
    note: typeof detail.message === 'string' ? detail.message : undefined,
  }
}

export function maintenanceSummaryFromGenerationPreview(
  payload: Record<string, unknown>,
  actionLabel: string,
): MaintenanceImpactSummary {
  const editedFiles = (payload.editedFiles as string[]) || []
  const staleFiles = (payload.staleFiles as string[]) || []
  const conflictFiles = (payload.conflictFiles as string[]) || []
  const hasConflict = Boolean(conflictFiles.length || editedFiles.length)

  return {
    actionLabel,
    status: hasConflict ? 'conflict' : 'preview',
    affectedFiles: (payload.affectedFiles as string[]) || [],
    changedFiles: (payload.changedFiles as string[]) || [],
    preservedFiles: (payload.preservedFiles as string[]) || [],
    editedFiles,
    staleFiles,
    conflictFiles,
    note: 'Preview does not rewrite generated files. Apply only after conflicts are resolved.',
  }
}

export function generationConflictGuidance(summary: MaintenanceImpactSummary): string[] {
  const guidance: string[] = []
  if (summary.conflictFiles?.length) {
    guidance.push(
      'Conflict files were edited in the IDE while their source mapping/structure also changed. Open each file, reconcile changes, or revert manual edits before regenerating.',
    )
  }
  if (summary.editedFiles?.length) {
    guidance.push(
      'Edited files contain manual IDE changes. Save copies elsewhere or revert edits in the affected files before regeneration can overwrite them.',
    )
  }
  if (summary.staleFiles?.length) {
    guidance.push(
      'Stale files have newer upstream source data. They can be refreshed after edited/conflict blockers are cleared.',
    )
  }
  if (!guidance.length) {
    guidance.push('Review the affected file list, then retry generation or use preview before apply.')
  }
  return guidance
}
