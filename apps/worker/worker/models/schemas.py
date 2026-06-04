from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


class FailureTargetResolution(BaseModel):
    status: Literal["resolved", "missing", "ambiguous"]
    reason: str
    execution_result_id: Optional[str] = None
    execution_run_id: Optional[str] = None
    project_id: Optional[str] = None
    automation_key: Optional[str] = None
    source_type: Optional[str] = None
    source_case_id: Optional[str] = None
    structured_step_id: Optional[str] = None
    page_object_method_id: Optional[str] = None
    test_case_ids: list[str] = Field(default_factory=list)
    generated_file_ids: list[str] = Field(default_factory=list)
    structured_flow_ids: list[str] = Field(default_factory=list)
    structured_step_ids: list[str] = Field(default_factory=list)
    page_object_method_ids: list[str] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)
    raw_action_ids: list[str] = Field(default_factory=list)
    webwright_run_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)


class FailureDispositionDiagnosis(BaseModel):
    execution_result_id: str
    automation_key: Optional[str] = None
    disposition: Literal[
        "selector_changed",
        "raw_refresh_required",
        "feature_removed_retire_tc",
        "unknown",
    ]
    reason: str
    confidence: float = Field(ge=0, le=1)
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    selector_candidate_ids: list[str] = Field(default_factory=list)
    target: FailureTargetResolution


class ExecutionDiagnosis(BaseModel):
    project_id: str
    execution_id: str
    diagnoses: list[FailureDispositionDiagnosis] = Field(default_factory=list)


class TestStep(BaseModel):
    index: int
    action: str
    expected: Optional[str] = None


class SourceLocation(BaseModel):
    file_path: Optional[str] = None
    sheet_name: Optional[str] = None
    row_index: Optional[int] = None
    api_endpoint: Optional[str] = None


class NormalizedTestCase(BaseModel):
    id: Optional[str] = None
    source_type: str
    source_id: str
    source_location: Optional[SourceLocation] = None
    title: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: Optional[str] = None
    automation_key: str
    tags: list[str] = Field(default_factory=list)
    priority: Optional[str] = None
    start_url: Optional[str] = None
    status: str = "imported"


class ExcelColumnMapping(BaseModel):
    case_id: str = "Case ID"
    title: str = "Title"
    precondition: str = "Precondition"
    step: str = "Step"
    expected: str = "Expected Result"
    priority: str = "Priority"
    automation_key: str = "Automation Key"
    start_url: str = "Start URL"


class ExcelPreviewRequest(BaseModel):
    file_path: str
    sheet_name: Optional[str] = None
    column_mapping: Optional[ExcelColumnMapping] = None


class ExcelImportRequest(BaseModel):
    file_path: str
    sheet_name: Optional[str] = None
    column_mapping: Optional[ExcelColumnMapping] = None
    selected_rows: Optional[list[int]] = None


class TestRailCloneImportRequest(BaseModel):
    project_id: str
    suite_id: Optional[str] = None


class TestRailImportRequest(BaseModel):
    project_id: int
    suite_id: Optional[int] = None


class GoogleSheetsImportRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str
    column_mapping: Optional[ExcelColumnMapping] = None


class WebwrightRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    case_ids: list[str] = Field(validation_alias=AliasChoices("caseIds", "case_ids"))
    mode: str = "sequential"
    ww_model_config: str = Field(default="model_openai.yaml", alias="modelConfig")
    start_url_override: Optional[str] = Field(default=None, alias="startUrlOverride")


class ActionItem(BaseModel):
    id: Optional[str] = None
    type: str
    target: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    source_line: Optional[int] = None
    order_index: int = 0


class MappingItem(BaseModel):
    id: Optional[str] = None
    tc_step_index: int
    action_ids: list[str] = Field(default_factory=list)
    normalized_step_id: Optional[str] = None
    normalized_step_name: Optional[str] = None
    pom_method_name: Optional[str] = None
    status: str = "mapped"


class MappingUpdateRequest(BaseModel):
    mappings: list[MappingItem]
    actions: Optional[list[ActionItem]] = None


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    env: str = "stg"
    browser: str = "chromium"
    headed: bool = False
    target_type: str = Field(default="all", alias="target_type")
    automation_key: Optional[str] = Field(default=None, alias="automation_key")
    case_ids: Optional[list[str]] = Field(default=None, alias="case_ids")
    result_target: str = Field(default="local", alias="result_target")


class ExportRequest(BaseModel):
    preview: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class FileContentUpdate(BaseModel):
    path: str
    content: str


class FileCreateRequest(BaseModel):
    path: str
    content: str = ""


class FileRenameRequest(BaseModel):
    old_path: str
    new_path: str


class AppSettings(BaseModel):
    runtime: dict[str, Any] = Field(default_factory=lambda: {
        "mode": "custom",
        "python": "",
        "webwrightRoot": "",
        "webwrightPython": "",
        "playwrightBrowsersPath": "",
        "templatePath": "",
    })
    webwright: dict[str, Any] = Field(default_factory=lambda: {
        "executionMode": "native",
        "root": "",
        "python": "",
        "baseConfig": "base.yaml",
        "modelConfig": "model_openai.yaml",
        "modelName": "",
        "apiProvider": "openai",
        "shell": "",
        "stepLimit": 30,
        "runTimeoutSeconds": 180,
        "outputRoot": "",
    })
    generator: dict[str, Any] = Field(default_factory=lambda: {
        "projectRoot": "",
        "defaultFramework": "playwright-pytest",
        "defaultLanguage": "python",
        "templatePath": "",
    })
    runner: dict[str, Any] = Field(default_factory=lambda: {
        "defaultBrowser": "chromium",
        "defaultEnv": "stg",
        "headless": True,
    })
    integrations: dict[str, Any] = Field(default_factory=lambda: {
        "testrailClone": {"baseUrl": "http://localhost:3000", "enabled": False},
        "testrail": {"baseUrl": "", "enabled": False},
        "googleSheets": {"enabled": False},
    })
