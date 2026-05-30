from __future__ import annotations

from worker.models.schemas import ExcelColumnMapping, NormalizedTestCase, TestStep


async def import_from_google_sheets(spreadsheet_id: str, sheet_name: str, mapping: ExcelColumnMapping | None) -> list[NormalizedTestCase]:
    # Placeholder for Google Sheets API integration
    return [
        NormalizedTestCase(
            source_type="google_sheets",
            source_id="GS-001",
            title="Sample Google Sheets Case",
            steps=[TestStep(index=1, action="Navigate", expected="Page visible")],
            automation_key="sample_google_sheets_case",
        )
    ]
