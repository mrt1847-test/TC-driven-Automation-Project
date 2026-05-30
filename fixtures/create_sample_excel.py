from openpyxl import Workbook
from pathlib import Path

wb = Workbook()
ws = wb.active
ws.title = "TestCases"
headers = ["Case ID", "Title", "Precondition", "Step", "Expected Result", "Priority", "Automation Key", "Start URL"]
ws.append(headers)
ws.append([
    "TC-001",
    "SRP 광고 상품 클릭 로그 검증",
    "STG 환경 접속 가능",
    "example.com 접속; More information 링크 클릭",
    "iana.org 도메인 페이지 표시; PDP 이동",
    "P2",
    "sample_case_001",
    "https://example.com",
])
out = Path(__file__).parent / "sample_cases.xlsx"
wb.save(out)
print(f"Created {out}")
