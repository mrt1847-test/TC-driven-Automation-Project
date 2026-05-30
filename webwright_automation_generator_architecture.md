# Webwright Automation Generator Architecture

## 1. 문서 목적

이 문서는 `webwright-automation-generator`를 GUI 기반의 **TC-driven Automation Project Studio**로 설계하기 위한 아키텍처 문서다.

이 도구의 목적은 단순히 Webwright를 실행하는 GUI를 만드는 것이 아니다. 핵심 목표는 다음과 같다.

1. TestRail, testrail-clone, Excel, Google Sheets 등에 존재하는 TC를 불러온다.
2. 각 TC를 Webwright를 통해 raw 자동화 코드로 변환한다.
3. raw 코드와 TC를 매핑한다.
4. raw 코드를 구조화하여 유지보수 가능한 자동화 프로젝트를 생성한다.
5. 생성된 자동화 프로젝트를 GUI에서 실행, 편집, 수정, 확장할 수 있게 한다.
6. 자동화 실행 결과를 원본 TC 관리 시스템 또는 문서로 다시 반영한다.

즉 이 제품은 **TC를 기준으로 자동화 코드를 생성하고, 구조화하고, 실행하고, 결과를 되돌려주는 로컬 QA 자동화 IDE**다.

---

## 2. 제품 정의

### 2.1 한 문장 정의

`webwright-automation-generator`는 TestRail, testrail-clone, Excel, Google Sheets의 TC를 불러와 Webwright 기반 raw 자동화 코드를 생성하고, 이를 구조화된 Playwright 자동화 프로젝트로 변환한 뒤, GUI에서 편집·실행·결과 반영까지 지원하는 로컬 QA 자동화 IDE다.

### 2.2 제품 성격

이 도구는 일반 웹서비스보다는 로컬 개발 도구에 가깝다.

비슷한 성격의 도구는 다음과 같다.

- VS Code
- Postman
- Insomnia
- Playwright UI 도구
- Cursor
- Test automation runner
- Test case management assistant

이 도구는 원격 SaaS가 아니라 **로컬 프로젝트 생성·편집·실행 도구**로 설계하는 것이 적절하다.

### 2.3 핵심 사용자

주요 사용자는 QA 자동화 담당자다.

사용자는 다음과 같은 상황을 가진다.

- 이미 TestRail, Excel, Google Sheets 등에 수동 TC가 존재한다.
- TC를 자동화 코드로 전환하고 싶다.
- Webwright를 통해 자동화 초안을 만들고 싶다.
- 그러나 Webwright의 raw code를 그대로 쓰는 것은 유지보수성이 낮다고 판단한다.
- 최종적으로는 POM, helper, fixture, runner, report 구조를 갖춘 실제 자동화 프로젝트를 만들고 싶다.
- GUI에서 자동화 코드를 수정하고 바로 실행해보고 싶다.
- 실행 결과를 다시 TC 관리 시스템에 반영하고 싶다.

---

## 3. 핵심 설계 원칙

## 3.1 TC 중심 설계

이 제품의 중심 객체는 코드가 아니라 TC다.

전체 흐름은 다음과 같다.

```text
TC
  ↓
Webwright raw code
  ↓
TC ↔ raw action mapping
  ↓
structured automation code
  ↓
execution result
  ↓
TC result update
```

모든 생성물은 `automationKey`를 기준으로 연결된다.

```text
Test Case
  automationKey: srp_ad_click_tracking_001

Raw Webwright Run
  automationKey: srp_ad_click_tracking_001

Structured Test
  automationKey: srp_ad_click_tracking_001

Execution Result
  automationKey: srp_ad_click_tracking_001

Result Export
  automationKey: srp_ad_click_tracking_001
```

따라서 `automationKey`는 이 시스템에서 가장 중요한 연결 키다.

---

## 3.2 Webwright raw code는 최종 산출물이 아니다

Webwright가 생성한 `final_script.py`는 최종 자동화 코드가 아니라 **구조화의 재료**다.

나쁜 흐름은 다음과 같다.

```text
TC
  ↓
Webwright final_script.py
  ↓
그대로 저장
  ↓
자동화 완료
```

이 방식은 빠르게 보이지만 유지보수성이 떨어진다.

올바른 흐름은 다음과 같다.

```text
TC
  ↓
Webwright final_script.py / trajectory.json
  ↓
action extraction
  ↓
normalized flow
  ↓
POM / helper / fixture / test file 생성
  ↓
generated automation project
```

즉 Webwright는 자동화 프로젝트를 완성하는 도구가 아니라 **초안을 생성하고 브라우저 조작 경로를 탐색하는 엔진**으로 사용한다.

---

## 3.3 GUI는 생성·편집·실행을 오케스트레이션한다

GUI는 테스트 로직을 직접 소유하지 않는다.

GUI의 역할은 다음과 같다.

- TC import 요청
- Webwright 실행 요청
- raw script 확인
- mapping 편집
- structured code 생성 요청
- generated project 파일 편집
- generated project 실행 요청
- artifact 표시
- result export 요청

반면 실제 자동화 실행 로직은 `generated automation project` 내부에 존재해야 한다.

```text
GUI
  - 버튼과 화면 제공
  - 실행 옵션 선택
  - 로그 표시
  - 결과 표시

Generated Automation Project
  - 실제 pytest/playwright 코드 보유
  - runner CLI 보유
  - results.json 생성
  - artifacts 생성
  - CI에서도 독립 실행 가능
```

이 원칙을 지켜야 GUI 없이도 generated project가 단독으로 실행될 수 있다.

---

## 3.4 testrail-clone은 자동화 코드를 소유하지 않는다

`testrail-clone`은 테스트 관리 시스템이다.

역할은 다음으로 제한한다.

- TC 제공
- automationKey 제공 또는 저장
- test run 제공
- result 수신
- coverage/report 표시

`testrail-clone`이 자동화 코드를 직접 저장하거나 실행하지 않는다.

자동화 코드는 다음 위치에 존재한다.

```text
Generated Automation Project
  ├─ tests/
  ├─ pages/
  ├─ flows/
  ├─ fixtures/
  ├─ runner/
  └─ config/
```

---

## 3.5 generated project는 독립 실행 가능해야 한다

생성된 자동화 프로젝트는 GUI 없이도 다음 명령으로 실행 가능해야 한다.

```bash
cd generated-automation-project
python -m runner.cli run --env stg --browser chromium --all
```

또는 특정 TC만 실행할 수 있어야 한다.

```bash
python -m runner.cli run \
  --env stg \
  --browser chromium \
  --case-key srp_ad_click_tracking_001
```

이 구조여야 CI에서도 동일한 명령을 사용할 수 있다.

---

## 4. 전체 시스템 아키텍처

## 4.1 상위 구조

```text
┌─────────────────────────────────────────────────────────────┐
│                    Electron + React GUI                     │
│                                                             │
│  - TC Import 화면                                           │
│  - Webwright Generate 화면                                  │
│  - Mapping & Review 화면                                    │
│  - Project IDE 화면                                         │
│  - Runner 화면                                              │
│  - Result Export 화면                                       │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTP / WebSocket / IPC
                                ↓
┌─────────────────────────────────────────────────────────────┐
│                  Local FastAPI Worker                       │
│                                                             │
│  - Case Import Service                                      │
│  - Webwright Run Service                                    │
│  - Mapping Service                                          │
│  - Structuring Service                                      │
│  - Project Generator Service                                │
│  - Project Runner Service                                   │
│  - Result Export Service                                    │
│  - Settings / Credential Service                            │
└───────────────────────────────┬─────────────────────────────┘
                                │ subprocess / file I/O / API
                                ↓
┌─────────────────────────────────────────────────────────────┐
│                    Local Tool Layer                         │
│                                                             │
│  - Webwright CLI                                            │
│  - Playwright                                               │
│  - Python venv                                              │
│  - Generated Automation Projects                            │
│  - SQLite                                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4.2 외부 시스템 연동 구조

```text
┌─────────────┐
│ TestRail    │
└──────┬──────┘
       │ import/export
       ↓
┌─────────────┐
│ testrail-   │
│ clone       │
└──────┬──────┘
       │ import/export
       ↓
┌─────────────┐
│ Excel       │
└──────┬──────┘
       │ import/export
       ↓
┌─────────────┐
│ Google      │
│ Sheets      │
└──────┬──────┘
       │ import/export
       ↓
┌─────────────────────────────────────────┐
│ webwright-automation-generator          │
│                                         │
│  - TC normalize                         │
│  - automationKey mapping                │
│  - raw code generation                  │
│  - structured project generation        │
│  - local execution                      │
│  - result export                        │
└─────────────────────────────────────────┘
```

---

## 4.3 데이터 흐름

```text
[TC Source]
  ↓ import
[Normalized Test Case]
  ↓ prompt build
[Webwright Run]
  ↓ artifact collect
[Raw Script + Trajectory]
  ↓ action extraction
[Raw Action List]
  ↓ mapping review
[TC Step ↔ Raw Action Mapping]
  ↓ normalization
[Normalized Flow]
  ↓ code generation
[Generated Automation Project]
  ↓ run
[Execution Result]
  ↓ export
[TC Source Result Update]
```

---

## 5. 주요 컴포넌트

## 5.1 Electron + React GUI

### 역할

GUI는 사용자가 전체 자동화 생성·편집·실행 흐름을 조작하는 진입점이다.

주요 기능은 다음과 같다.

- 프로젝트 생성 및 선택
- TC source 연결
- TC import
- Webwright 실행
- raw script 확인
- action mapping 편집
- structured project 생성
- 생성된 파일 수정
- 테스트 실행
- 실행 결과 확인
- 결과 export

### 추천 기술

```text
Electron
React
TypeScript
Tailwind CSS
Monaco Editor
xterm.js
React Query 또는 TanStack Query
Zustand 또는 Redux Toolkit
```

### GUI 주요 화면

```text
1. Welcome / Setup Wizard
2. Project Dashboard
3. TC Import
4. TC List
5. Webwright Generate
6. Mapping & Review
7. Project IDE
8. Runner
9. Execution Result
10. Result Export
11. Settings
```

---

## 5.2 Local FastAPI Worker

### 역할

FastAPI Worker는 GUI와 로컬 도구 사이의 중간 계층이다.

GUI가 직접 Webwright나 pytest를 실행하지 않고, Worker에게 요청한다.

Worker의 역할은 다음과 같다.

- 로컬 설정 관리
- Webwright 설치 확인
- Python venv 확인
- Playwright browser 설치 확인
- Webwright CLI 실행
- generated project 생성
- generated project 실행
- 로그 스트리밍
- artifact 수집
- 결과 파싱
- 외부 시스템 API 연동

### 추천 기술

```text
Python 3.11+
FastAPI
Uvicorn
Pydantic
SQLAlchemy 또는 SQLModel
SQLite
subprocess / asyncio subprocess
watchdog
openpyxl
requests 또는 httpx
```

### 통신 방식

GUI와 Worker는 기본적으로 HTTP API로 통신한다.

실시간 로그는 WebSocket 또는 Server-Sent Events를 사용한다.

```text
GUI
  ├─ HTTP: 실행 요청, 조회 요청, 저장 요청
  └─ WebSocket/SSE: 실행 로그, 진행률, 상태 업데이트

Worker
  ├─ REST API
  ├─ log stream
  └─ background process manager
```

---

## 5.3 SQLite Local Database

### 역할

SQLite는 로컬 프로젝트의 메타데이터를 저장한다.

코드 파일 자체를 DB에 저장하지 않는다. 코드는 파일시스템에 저장한다.

DB에는 다음 정보만 저장한다.

- 프로젝트 목록
- TC import 이력
- normalized test case
- automationKey
- Webwright run 상태
- raw artifact 경로
- mapping 정보
- generated file 경로
- execution run 정보
- result export 상태

### 이유

- 로컬 도구에 적합하다.
- 설치가 쉽다.
- 단일 사용자 환경에 충분하다.
- 파일 기반 프로젝트와 함께 관리하기 좋다.

---

## 5.4 Webwright CLI Adapter

### 역할

Webwright CLI Adapter는 Webwright 실행을 감싸는 계층이다.

GUI나 상위 서비스가 Webwright 명령어를 직접 알 필요가 없게 한다.

### 책임

- Webwright root 경로 확인
- Webwright python 경로 확인
- config 파일 확인
- API key 환경변수 주입
- TC를 Webwright task prompt로 변환
- Webwright CLI 실행
- stdout/stderr 수집
- final_script.py 경로 확인
- trajectory.json 경로 확인
- screenshots/logs 수집
- 실패 시 error classification

### 실행 예시

```bash
python -m webwright.run.cli \
  -c base.yaml \
  -c model_openai.yaml \
  -t "<TC 기반 task prompt>" \
  --start-url "<start url>" \
  --task-id "<automationKey>" \
  -o "<webwright output root>"
```

Windows + WSL 구조에서는 다음과 같이 실행할 수 있다.

```bash
wsl.exe bash -lc "
cd ~/qa-tools/Webwright &&
source .venv/bin/activate &&
python -m webwright.run.cli \
  -c base.yaml \
  -c model_openai.yaml \
  -t '<task>' \
  --start-url '<url>' \
  --task-id '<automationKey>' \
  -o '<output_root>'
"
```

---

## 5.5 Case Import Service

### 역할

Case Import Service는 외부 TC source에서 TC를 가져와 내부 표준 모델로 변환한다.

지원 대상은 다음과 같다.

- Excel
- testrail-clone
- TestRail
- Google Sheets

### 내부 표준 모델

모든 source의 TC는 아래 구조로 변환된다.

```json
{
  "id": "local_tc_001",
  "sourceType": "excel",
  "sourceId": "TC-001",
  "sourceLocation": {
    "filePath": "/cases/sample.xlsx",
    "sheetName": "TestCases",
    "rowIndex": 12
  },
  "title": "SRP 광고 상품 클릭 로그 검증",
  "preconditions": [
    "STG 환경에 접속 가능해야 한다",
    "테스트 계정이 준비되어 있어야 한다"
  ],
  "steps": [
    {
      "index": 1,
      "action": "SRP 페이지에 진입한다",
      "expected": "검색 결과 페이지가 노출된다"
    },
    {
      "index": 2,
      "action": "광고 상품을 클릭한다",
      "expected": "PDP로 이동한다"
    }
  ],
  "expectedResult": "클릭 로그가 정상 발생한다",
  "automationKey": "srp_ad_click_tracking_001",
  "tags": ["srp", "ad", "click-log"],
  "priority": "P2"
}
```

### Excel Import

초기 MVP에서는 Excel import를 먼저 지원한다.

Excel은 인증이 필요 없고 로컬에서 독립적으로 테스트하기 좋다.

필요 기능은 다음과 같다.

- 파일 선택
- sheet 선택
- column mapping 설정
- preview
- import
- automationKey 자동 생성
- 중복 TC 감지

예상 column mapping:

```text
Case ID
Title
Precondition
Step
Expected Result
Priority
Automation Key
Result
Comment
```

### testrail-clone Import

testrail-clone은 자체 API를 제공하므로 두 번째 단계에서 붙이는 것이 좋다.

예상 API:

```http
GET /api/automation/cases?projectId=...&suiteId=...
```

응답:

```json
{
  "cases": [
    {
      "caseId": "tc_abc123",
      "title": "SRP 광고 클릭 로그 검증",
      "steps": [],
      "automationKey": "srp_ad_click_tracking_001"
    }
  ]
}
```

### TestRail Import

TestRail은 실제 API token, project id, suite id, run id 등 설정이 필요하므로 MVP 이후에 지원한다.

### Google Sheets Import

Google Sheets는 OAuth 또는 service account 설정이 필요하므로 Excel보다 후순위로 둔다.

---

## 5.6 Prompt Builder

### 역할

Prompt Builder는 normalized TC를 Webwright task prompt로 변환한다.

Webwright는 자연어 task를 받아 브라우저 조작과 코드 생성을 수행하므로, TC를 그대로 던지는 것보다 자동화 목적에 맞게 정리해야 한다.

### 입력

```text
- TC title
- startUrl
- preconditions
- steps
- expected result
- environment
- known selectors
- login state
- test account info reference
- validation target
```

### 출력 예시

```text
You are generating a Playwright Python automation draft for the following QA test case.

Automation Key:
srp_ad_click_tracking_001

Start URL:
https://m-stg.gmarket.co.kr/n/search?keyword=ipad

Goal:
Verify that clicking an ad product on the search result page opens the product detail page and emits the expected click tracking log.

Steps:
1. Open the search result page.
2. Find the first visible ad product card.
3. Click the ad product.
4. Verify that the product detail page is opened.
5. Verify that a click tracking request containing /Product.Click.Event is emitted.

Constraints:
- Prefer stable selectors.
- Avoid hard-coded dynamic ids.
- Add explicit waits where necessary.
- Produce a final Playwright Python script.
```

### 주의점

Prompt Builder는 TC를 과도하게 변형하면 안 된다.

TC의 원래 의도를 보존하되, Webwright가 실행 가능한 지시문으로 바꿔야 한다.

---

## 5.7 Webwright Run Service

### 역할

Webwright Run Service는 TC별 Webwright 실행을 관리한다.

### 실행 단위

기본 실행 단위는 다음과 같다.

```text
1 TC = 1 Webwright Run
```

이 방식이 좋은 이유:

- TC와 artifact 매핑이 명확하다.
- 실패한 TC만 재시도하기 쉽다.
- 비용과 시간을 추적하기 쉽다.
- raw script와 automationKey 연결이 단순하다.

### 상태 모델

```text
pending
running
completed
failed
cancelled
needs_review
structured
generated
```

### 저장 artifact

```text
webwright-runs/
  └─ srp_ad_click_tracking_001/
      └─ run_20260530_001/
          ├─ final_script.py
          ├─ trajectory.json
          ├─ stdout.log
          ├─ stderr.log
          ├─ screenshots/
          └─ metadata.json
```

### metadata.json 예시

```json
{
  "runId": "run_20260530_001",
  "automationKey": "srp_ad_click_tracking_001",
  "caseId": "TC-001",
  "sourceType": "excel",
  "startUrl": "https://m-stg.gmarket.co.kr/n/search?keyword=ipad",
  "status": "completed",
  "startedAt": "2026-05-30T19:00:00+09:00",
  "endedAt": "2026-05-30T19:05:12+09:00",
  "artifacts": {
    "finalScript": "final_script.py",
    "trajectory": "trajectory.json",
    "stdout": "stdout.log",
    "stderr": "stderr.log"
  }
}
```

---

## 5.8 Action Extraction Service

### 역할

Action Extraction Service는 Webwright raw script와 trajectory에서 자동화 action을 추출한다.

### 입력

```text
final_script.py
trajectory.json
screenshots
stdout/stderr logs
```

### 출력

```json
{
  "automationKey": "srp_ad_click_tracking_001",
  "actions": [
    {
      "id": "act_001",
      "type": "goto",
      "target": "https://m-stg.gmarket.co.kr/n/search?keyword=ipad",
      "selector": null,
      "value": null,
      "sourceLine": 12
    },
    {
      "id": "act_002",
      "type": "click",
      "target": "first ad product card",
      "selector": "page.locator('[data-testid=ad-product]').first",
      "value": null,
      "sourceLine": 24
    },
    {
      "id": "act_003",
      "type": "assert_url",
      "target": "product detail page",
      "selector": null,
      "value": "/item",
      "sourceLine": 31
    }
  ]
}
```

### 추출 대상 action

```text
goto
click
fill
select
check
uncheck
hover
press
wait
wait_for_request
wait_for_response
assert_text
assert_url
assert_visible
assert_hidden
assert_count
custom_code
```

### 주의점

처음부터 완벽한 AST 분석을 목표로 하지 않는다.

MVP에서는 다음 순서로 접근한다.

1. final_script.py 라인 기반 추출
2. Playwright API 패턴 기반 추출
3. trajectory.json 보조 활용
4. 이후 Python AST 기반 고도화

---

## 5.9 Mapping & Review Service

### 역할

Mapping & Review Service는 TC step과 raw action을 연결한다.

이 단계가 제품 품질의 핵심이다.

Webwright raw code를 그대로 구조화하면 잘못된 코드가 만들어질 수 있다. 따라서 사용자가 GUI에서 다음을 검토해야 한다.

- TC step과 action의 연결이 맞는가?
- 불필요한 action은 없는가?
- selector가 안정적인가?
- assert가 충분한가?
- 공통 flow로 추출할 수 있는가?
- POM 메서드로 분리할 수 있는가?

### 화면 구조

```text
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ TC Steps             │ Raw Actions           │ Normalized Flow       │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ 1. SRP 진입          │ goto(...)             │ open_search_page      │
│ 2. 광고 상품 클릭    │ click(...)            │ click_ad_product      │
│ 3. PDP 진입 확인     │ expect(url)           │ verify_pdp_opened     │
│ 4. 로그 확인         │ wait_for_request(...) │ verify_click_log      │
└──────────────────────┴──────────────────────┴──────────────────────┘
```

### mapping 모델

```json
{
  "automationKey": "srp_ad_click_tracking_001",
  "mappings": [
    {
      "tcStepIndex": 1,
      "actionIds": ["act_001"],
      "normalizedStepId": "flow_001",
      "status": "mapped"
    },
    {
      "tcStepIndex": 2,
      "actionIds": ["act_002"],
      "normalizedStepId": "flow_002",
      "status": "mapped"
    }
  ]
}
```

### 지원 편집 기능

```text
- action 삭제
- action 순서 변경
- action type 변경
- selector 수정
- value 수정
- assertion 추가
- wait 추가
- normalized step 이름 변경
- 공통 flow로 추출
- POM method 이름 지정
```

---

## 5.10 Structuring Service

### 역할

Structuring Service는 raw action과 mapping 정보를 기반으로 유지보수 가능한 자동화 코드 구조를 생성한다.

### 입력

```text
normalized test case
action list
mapping
user review edits
project template
coding convention
```

### 출력

```text
tests/
pages/
flows/
fixtures/
config/
runner/
mapping.yaml
```

### 변환 단계

```text
Raw Action List
  ↓
Reviewed Action List
  ↓
Normalized Flow
  ↓
Page Object Method 후보 생성
  ↓
Flow Function 생성
  ↓
Test Function 생성
  ↓
Runner Mapping 생성
  ↓
Project Files 생성
```

### 예시 변환

Raw action:

```python
page.goto("https://m-stg.gmarket.co.kr/n/search?keyword=ipad")
page.locator("[data-testid='ad-product']").first.click()
expect(page).to_have_url(re.compile(".*item.*"))
```

Structured code:

```python
# pages/search_page.py
class SearchPage:
    def __init__(self, page):
        self.page = page

    def open(self, keyword: str):
        self.page.goto(f"/n/search?keyword={keyword}")

    def click_first_ad_product(self):
        self.page.locator("[data-testid='ad-product']").first.click()
```

```python
# flows/srp_ad_click_flow.py
class SrpAdClickFlow:
    def __init__(self, page):
        self.search_page = SearchPage(page)
        self.product_page = ProductPage(page)

    def execute(self, keyword: str):
        self.search_page.open(keyword)
        self.search_page.click_first_ad_product()
        self.product_page.verify_opened()
```

```python
# tests/test_srp_ad_click_tracking.py
def test_srp_ad_click_tracking(page, log_collector):
    flow = SrpAdClickFlow(page)
    flow.execute(keyword="ipad")
    log_collector.assert_event_exists("/Product.Click.Event")
```

---

## 5.11 Project Generator Service

### 역할

Project Generator Service는 structured code와 template을 기반으로 실제 자동화 프로젝트를 생성한다.

### 생성 프로젝트 구조

```text
generated-automation-project/
  ├─ tests/
  │   └─ test_srp_ad_click_tracking.py
  ├─ pages/
  │   ├─ search_page.py
  │   └─ product_page.py
  ├─ flows/
  │   └─ srp_ad_click_flow.py
  ├─ fixtures/
  │   ├─ browser_fixture.py
  │   └─ log_collector_fixture.py
  ├─ config/
  │   ├─ env.local.json
  │   ├─ env.stg.json
  │   ├─ env.prod.json
  │   └─ automation.yaml
  ├─ runner/
  │   ├─ __init__.py
  │   ├─ cli.py
  │   ├─ mapping_loader.py
  │   ├─ result_parser.py
  │   ├─ result_writer.py
  │   ├─ testrail_uploader.py
  │   ├─ testrail_clone_uploader.py
  │   ├─ excel_writer.py
  │   └─ google_sheets_writer.py
  ├─ artifacts/
  │   └─ runs/
  ├─ mappings/
  │   └─ cases.yaml
  ├─ requirements.txt
  ├─ pytest.ini
  ├─ README.md
  └─ .gitignore
```

### 생성 원칙

- GUI 없이도 실행 가능해야 한다.
- 테스트 실행 진입점은 `runner.cli`다.
- 결과는 표준 `results.json`으로 저장한다.
- 원본 TC와의 연결은 `mappings/cases.yaml`에 저장한다.
- page object, flow, test는 사람이 수정 가능한 코드로 생성한다.
- generated project는 Git repo로 관리할 수 있어야 한다.

---

## 5.12 Project IDE Service

### 역할

Project IDE Service는 생성된 자동화 프로젝트를 GUI에서 열고 수정할 수 있게 한다.

### 주요 기능

```text
- 프로젝트 파일 트리 표시
- 파일 열기
- 코드 편집
- 저장
- 새 파일 생성
- 파일 삭제
- 파일 이름 변경
- automationKey 검색
- selector 검색
- 연결된 TC 보기
- 특정 파일 기준 테스트 실행
- 특정 automationKey 기준 테스트 실행
```

### GUI 구성

```text
┌──────────────────────┬────────────────────────────────┬──────────────────────┐
│ File Tree            │ Code Editor                    │ Context Panel        │
│                      │                                │                      │
│ tests/               │ def test_srp_ad_click...       │ TC Info              │
│ pages/               │                                │ Mapping              │
│ flows/               │                                │ Last Result          │
│ fixtures/            │                                │ Artifacts            │
└──────────────────────┴────────────────────────────────┴──────────────────────┘
│ Terminal / Runner Log / Problems                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Monaco Editor 사용

Monaco Editor를 사용하면 다음 기능을 쉽게 제공할 수 있다.

- Python syntax highlight
- JSON/YAML syntax highlight
- 검색
- 다중 파일 탭
- 단축키 저장
- diff viewer

단, 완전한 VS Code 수준의 IDE를 목표로 하지 않는다.

목표는 **자동화 프로젝트 전용 미니 IDE**다.

---

## 5.13 Project Runner Service

### 역할

Project Runner Service는 generated automation project를 실행한다.

중요한 점은 GUI가 pytest/playwright 실행 규칙을 직접 소유하지 않는다는 것이다.

GUI와 Worker는 generated project의 runner CLI를 호출한다.

### 실행 명령 예시

전체 실행:

```bash
python -m runner.cli run \
  --env stg \
  --browser chromium \
  --all
```

특정 TC 실행:

```bash
python -m runner.cli run \
  --env stg \
  --browser chromium \
  --case-key srp_ad_click_tracking_001
```

실패 TC 재실행:

```bash
python -m runner.cli rerun-failed \
  --from-run-id 20260530_001
```

결과 업로드 포함:

```bash
python -m runner.cli run \
  --env stg \
  --browser chromium \
  --case-key srp_ad_click_tracking_001 \
  --result-target testrail-clone
```

### GUI 실행 옵션

```text
Environment:
- local
- stg
- prod

Browser:
- chromium
- firefox
- webkit

Mode:
- headless
- headed

Target:
- all
- selected cases
- selected suite
- failed cases

Result Target:
- local only
- testrail-clone
- TestRail
- Excel
- Google Sheets
```

### 실행 artifact 구조

```text
artifacts/
  └─ runs/
      └─ 20260530_001/
          ├─ results.json
          ├─ junit.xml
          ├─ stdout.log
          ├─ stderr.log
          ├─ screenshots/
          ├─ traces/
          └─ videos/
```

### results.json 예시

```json
{
  "runId": "20260530_001",
  "projectName": "gmarket-mweb-ad-automation",
  "env": "stg",
  "browser": "chromium",
  "startedAt": "2026-05-30T20:00:00+09:00",
  "endedAt": "2026-05-30T20:04:12+09:00",
  "summary": {
    "total": 10,
    "passed": 8,
    "failed": 1,
    "skipped": 1
  },
  "cases": [
    {
      "automationKey": "srp_ad_click_tracking_001",
      "sourceType": "excel",
      "sourceCaseId": "TC-001",
      "title": "SRP 광고 상품 클릭 로그 검증",
      "status": "passed",
      "durationMs": 42100,
      "error": null,
      "artifacts": {
        "screenshot": null,
        "trace": "traces/srp_ad_click_tracking_001.zip",
        "video": null
      }
    },
    {
      "automationKey": "lp_ad_exposure_001",
      "sourceType": "excel",
      "sourceCaseId": "TC-002",
      "title": "LP 광고 노출 로그 검증",
      "status": "failed",
      "durationMs": 58100,
      "error": "Expected /Product.Exposure.Event but not found",
      "artifacts": {
        "screenshot": "screenshots/lp_ad_exposure_001.png",
        "trace": "traces/lp_ad_exposure_001.zip",
        "video": null
      }
    }
  ]
}
```

---

## 5.14 Result Export Service

### 역할

Result Export Service는 실행 결과를 원래 TC source에 반영한다.

지원 대상:

- testrail-clone
- TestRail
- Excel
- Google Sheets

### 공통 입력

```text
results.json
mappings/cases.yaml
export target config
```

### source별 동작

#### testrail-clone

```http
POST /api/automation/results/bulk
```

요청 예시:

```json
{
  "runId": "20260530_001",
  "results": [
    {
      "automationKey": "srp_ad_click_tracking_001",
      "status": "passed",
      "durationMs": 42100,
      "comment": "Automation passed",
      "artifacts": []
    }
  ]
}
```

#### TestRail

TestRail은 case id 또는 run id 기준으로 result를 추가한다.

필요 정보:

```text
TestRail baseUrl
username
apiKey
projectId
runId
caseId
statusId
comment
elapsed
defects
```

#### Excel

Excel은 원본 파일 또는 복사본에 결과를 쓴다.

권장 방식:

```text
원본 파일 직접 수정: 위험
복사본 생성 후 결과 업데이트: 권장
```

예상 업데이트 column:

```text
Automation Result
Automation Run ID
Automation Executed At
Automation Comment
Artifact Path
```

#### Google Sheets

Google Sheets는 sheet id, worksheet name, row index 기준으로 업데이트한다.

필요 정보:

```text
spreadsheetId
sheetName
rowIndex
resultColumn
commentColumn
executedAtColumn
```

---

## 6. 내부 데이터 모델

## 6.1 Project

```json
{
  "id": "proj_001",
  "name": "gmarket-mweb-ad-automation",
  "rootPath": "/home/user/automation-projects/gmarket-mweb",
  "generatedProjectPath": "/home/user/automation-projects/gmarket-mweb/generated",
  "defaultEnv": "stg",
  "createdAt": "2026-05-30T20:00:00+09:00",
  "updatedAt": "2026-05-30T20:00:00+09:00"
}
```

## 6.2 TestCase

```json
{
  "id": "tc_local_001",
  "projectId": "proj_001",
  "sourceType": "excel",
  "sourceCaseId": "TC-001",
  "automationKey": "srp_ad_click_tracking_001",
  "title": "SRP 광고 상품 클릭 로그 검증",
  "stepsJson": [],
  "expectedResult": "클릭 로그 발생",
  "status": "imported"
}
```

## 6.3 WebwrightRun

```json
{
  "id": "ww_run_001",
  "projectId": "proj_001",
  "testCaseId": "tc_local_001",
  "automationKey": "srp_ad_click_tracking_001",
  "status": "completed",
  "outputPath": "/webwright-runs/srp_ad_click_tracking_001/run_001",
  "finalScriptPath": "/webwright-runs/srp_ad_click_tracking_001/run_001/final_script.py",
  "trajectoryPath": "/webwright-runs/srp_ad_click_tracking_001/run_001/trajectory.json"
}
```

## 6.4 RawAction

```json
{
  "id": "act_001",
  "webwrightRunId": "ww_run_001",
  "automationKey": "srp_ad_click_tracking_001",
  "orderIndex": 1,
  "type": "click",
  "selector": "[data-testid='ad-product']",
  "value": null,
  "sourceLine": 24
}
```

## 6.5 CaseActionMapping

```json
{
  "id": "map_001",
  "testCaseId": "tc_local_001",
  "rawActionId": "act_001",
  "tcStepIndex": 2,
  "normalizedStepId": "flow_002",
  "status": "mapped"
}
```

## 6.6 ExecutionRun

```json
{
  "id": "exec_001",
  "projectId": "proj_001",
  "runId": "20260530_001",
  "env": "stg",
  "browser": "chromium",
  "status": "completed",
  "resultPath": "/artifacts/runs/20260530_001/results.json"
}
```

## 6.7 ExecutionResult

```json
{
  "id": "exec_result_001",
  "executionRunId": "exec_001",
  "automationKey": "srp_ad_click_tracking_001",
  "status": "passed",
  "durationMs": 42100,
  "error": null,
  "screenshotPath": null,
  "tracePath": "traces/srp_ad_click_tracking_001.zip"
}
```

---

## 7. Local API 설계

## 7.1 Project API

```http
GET /projects
POST /projects
GET /projects/{projectId}
PATCH /projects/{projectId}
DELETE /projects/{projectId}
```

## 7.2 Case Import API

```http
POST /projects/{projectId}/cases/import/excel
POST /projects/{projectId}/cases/import/testrail-clone
POST /projects/{projectId}/cases/import/testrail
POST /projects/{projectId}/cases/import/google-sheets
GET /projects/{projectId}/cases
GET /projects/{projectId}/cases/{caseId}
PATCH /projects/{projectId}/cases/{caseId}
```

## 7.3 Webwright Run API

```http
POST /projects/{projectId}/webwright-runs
GET /projects/{projectId}/webwright-runs
GET /projects/{projectId}/webwright-runs/{runId}
POST /projects/{projectId}/webwright-runs/{runId}/cancel
POST /projects/{projectId}/webwright-runs/{runId}/retry
```

요청:

```json
{
  "caseIds": ["tc_local_001", "tc_local_002"],
  "mode": "sequential",
  "modelConfig": "model_openai.yaml"
}
```

## 7.4 Mapping API

```http
GET /projects/{projectId}/cases/{caseId}/actions
GET /projects/{projectId}/cases/{caseId}/mappings
PUT /projects/{projectId}/cases/{caseId}/mappings
POST /projects/{projectId}/cases/{caseId}/normalize
```

## 7.5 Project Generation API

```http
POST /projects/{projectId}/generate
GET /projects/{projectId}/generated-files
GET /projects/{projectId}/generated-files/content?path=...
PUT /projects/{projectId}/generated-files/content
POST /projects/{projectId}/generated-files/create
DELETE /projects/{projectId}/generated-files
```

## 7.6 Runner API

```http
POST /projects/{projectId}/executions
GET /projects/{projectId}/executions
GET /projects/{projectId}/executions/{executionId}
POST /projects/{projectId}/executions/{executionId}/cancel
POST /projects/{projectId}/executions/{executionId}/rerun-failed
```

요청:

```json
{
  "env": "stg",
  "browser": "chromium",
  "headed": false,
  "target": {
    "type": "case",
    "automationKey": "srp_ad_click_tracking_001"
  },
  "resultTarget": "local"
}
```

## 7.7 Result Export API

```http
POST /projects/{projectId}/executions/{executionId}/export/testrail-clone
POST /projects/{projectId}/executions/{executionId}/export/testrail
POST /projects/{projectId}/executions/{executionId}/export/excel
POST /projects/{projectId}/executions/{executionId}/export/google-sheets
```

---

## 8. 설정 구조

## 8.1 App Settings

```json
{
  "webwright": {
    "executionMode": "wsl",
    "root": "/home/user/qa-tools/Webwright",
    "python": "/home/user/qa-tools/Webwright/.venv/bin/python",
    "baseConfig": "base.yaml",
    "modelConfig": "model_openai.yaml",
    "outputRoot": "/home/user/qa-tools/webwright-runs"
  },
  "generator": {
    "projectRoot": "/home/user/automation-projects",
    "defaultFramework": "playwright-pytest",
    "defaultLanguage": "python"
  },
  "runner": {
    "defaultBrowser": "chromium",
    "defaultEnv": "stg",
    "headless": true
  },
  "integrations": {
    "testrailClone": {
      "baseUrl": "http://localhost:3000",
      "enabled": true
    },
    "testrail": {
      "baseUrl": "https://example.testrail.io",
      "enabled": false
    },
    "googleSheets": {
      "enabled": false
    }
  }
}
```

## 8.2 Credential 관리

API key와 token은 settings JSON에 평문 저장하지 않는다.

권장 저장소:

```text
Windows Credential Manager
macOS Keychain
Linux Secret Service
Electron keytar
```

저장 대상:

```text
OpenAI API Key
Anthropic API Key
OpenRouter API Key
TestRail API Key
testrail-clone API Token
Google OAuth Token
```

---

## 9. generated automation project 상세 설계

## 9.1 목적

Generated project는 실제 자동화 실행 단위다.

GUI 없이도 독립 실행 가능해야 하며, CI에서도 동일한 방식으로 실행되어야 한다.

## 9.2 프로젝트 구조

```text
generated-automation-project/
  ├─ tests/
  │   ├─ test_srp_ad_click_tracking.py
  │   └─ test_lp_ad_exposure.py
  │
  ├─ pages/
  │   ├─ base_page.py
  │   ├─ search_page.py
  │   ├─ product_page.py
  │   └─ cart_page.py
  │
  ├─ flows/
  │   ├─ srp_ad_click_flow.py
  │   └─ lp_ad_exposure_flow.py
  │
  ├─ fixtures/
  │   ├─ browser_fixture.py
  │   ├─ auth_fixture.py
  │   ├─ log_collector_fixture.py
  │   └─ env_fixture.py
  │
  ├─ config/
  │   ├─ env.local.json
  │   ├─ env.stg.json
  │   ├─ env.prod.json
  │   └─ automation.yaml
  │
  ├─ mappings/
  │   └─ cases.yaml
  │
  ├─ runner/
  │   ├─ __init__.py
  │   ├─ cli.py
  │   ├─ pytest_runner.py
  │   ├─ mapping_loader.py
  │   ├─ result_parser.py
  │   ├─ result_writer.py
  │   ├─ testrail_clone_uploader.py
  │   ├─ testrail_uploader.py
  │   ├─ excel_writer.py
  │   └─ google_sheets_writer.py
  │
  ├─ artifacts/
  │   └─ runs/
  │
  ├─ requirements.txt
  ├─ pytest.ini
  ├─ README.md
  └─ .gitignore
```

## 9.3 cases.yaml

```yaml
cases:
  - automationKey: srp_ad_click_tracking_001
    sourceType: excel
    sourceCaseId: TC-001
    title: SRP 광고 상품 클릭 로그 검증
    testFile: tests/test_srp_ad_click_tracking.py
    testFunction: test_srp_ad_click_tracking
    tags:
      - srp
      - ad
      - click-log
    resultTargets:
      excel:
        file: imported_cases.xlsx
        sheet: TestCases
        row: 12
      testrailClone:
        caseId: tc_abc123
      testrail:
        caseId: 12345
```

## 9.4 runner CLI

### run

```bash
python -m runner.cli run --env stg --browser chromium --all
```

```bash
python -m runner.cli run --env stg --browser chromium --case-key srp_ad_click_tracking_001
```

### rerun-failed

```bash
python -m runner.cli rerun-failed --from-run-id 20260530_001
```

### export

```bash
python -m runner.cli export --run-id 20260530_001 --target testrail-clone
```

### list-cases

```bash
python -m runner.cli list-cases
```

---

## 10. GUI 화면 상세

## 10.1 Setup Wizard

첫 실행 시 필요한 설정을 확인한다.

```text
1. Webwright Root 선택
2. Python venv 선택
3. API Provider 선택
4. API Key 등록
5. Playwright browser 설치 확인
6. Smoke Test 실행
7. 기본 프로젝트 경로 설정
```

버튼:

```text
[Check Webwright]
[Check Python]
[Check API Key]
[Install Chromium]
[Run Smoke Test]
```

---

## 10.2 Project Dashboard

프로젝트 목록과 최근 실행 결과를 보여준다.

```text
Project
- gmarket-mweb-ad-automation
- gmarket-app-regression

Recent Runs
- 20260530_001: 8 passed, 1 failed, 1 skipped
- 20260529_003: 10 passed
```

---

## 10.3 TC Import 화면

```text
Source Type:
- Excel
- testrail-clone
- TestRail
- Google Sheets

Import Source:
- File path
- API endpoint
- Project/Suite/Run
- Sheet ID

Column Mapping:
- Case ID
- Title
- Step
- Expected
- Automation Key
```

Preview table:

```text
| Select | Source | Case ID | Automation Key | Title | Steps | Status |
|--------|--------|---------|----------------|-------|-------|--------|
| ☑      | Excel  | TC-001  | srp_ad_001     | SRP 광고 클릭 | 5 | Ready |
```

---

## 10.4 Webwright Generate 화면

```text
| TC | Automation Key | Status | Raw Script | Log | Retry |
|----|----------------|--------|------------|-----|-------|
| TC-001 | srp_ad_001 | Completed | Open | Open | - |
| TC-002 | lp_ad_001  | Failed    | -    | Open | Retry |
```

기능:

```text
[Run Selected]
[Stop]
[Retry Failed]
[Open Output Folder]
```

---

## 10.5 Mapping & Review 화면

```text
Left: TC Steps
Center: Raw Actions
Right: Normalized Flow
Bottom: Raw code / Screenshot / Logs
```

사용자는 여기서 Webwright 결과를 자동화 프로젝트로 변환하기 전에 검토한다.

---

## 10.6 Project IDE 화면

```text
Left: File Tree
Center: Monaco Editor
Right: TC Context / Mapping / Last Result
Bottom: Terminal / Runner Log
```

주요 버튼:

```text
[Save]
[Run Current Test]
[Run Linked TC]
[Open Trace]
[Open Screenshot]
[Generate Again]
```

---

## 10.7 Runner 화면

```text
Target:
- All
- Selected Cases
- Failed Cases

Environment:
- local
- stg
- prod

Browser:
- chromium
- firefox
- webkit

Mode:
- headless
- headed

Result Target:
- local only
- testrail-clone
- TestRail
- Excel
- Google Sheets
```

---

## 10.8 Result 화면

```text
Summary
- Total: 10
- Pass: 8
- Fail: 1
- Skip: 1
- Duration: 4m 12s

Case Results
| Status | Automation Key | Title | Duration | Error |
|--------|----------------|-------|----------|-------|
| PASS | srp_ad_001 | SRP 광고 클릭 | 42s | - |
| FAIL | lp_ad_001 | LP 광고 노출 | 58s | Event not found |

Artifacts
- screenshot
- trace.zip
- stdout.log
- stderr.log
```

---

## 11. 실행 시퀀스

## 11.1 TC Import 시퀀스

```text
User
  → GUI: Excel 파일 선택
  → Worker: import 요청
  → Case Import Service: Excel parse
  → Case Import Service: column mapping 적용
  → Case Import Service: normalized TC 생성
  → SQLite: TC 저장
  → GUI: TC 목록 표시
```

## 11.2 Webwright Generate 시퀀스

```text
User
  → GUI: Run Selected 클릭
  → Worker: Webwright run 요청
  → Prompt Builder: TC → task prompt 변환
  → Webwright CLI Adapter: subprocess 실행
  → Webwright: final_script.py 생성
  → Worker: artifact 수집
  → Action Extraction Service: action list 생성
  → SQLite: run/action 저장
  → GUI: 완료 상태 표시
```

## 11.3 Mapping Review 시퀀스

```text
User
  → GUI: TC 선택
  → Worker: TC/action/mapping 조회
  → GUI: 3-pane review 표시
  → User: selector/action/flow 수정
  → Worker: mapping 저장
  → SQLite: mapping 업데이트
```

## 11.4 Project Generation 시퀀스

```text
User
  → GUI: Generate Project 클릭
  → Worker: generation 요청
  → Structuring Service: normalized flow 생성
  → Project Generator: files 생성
  → SQLite: generated file metadata 저장
  → GUI: Project IDE 표시
```

## 11.5 Project Execution 시퀀스

```text
User
  → GUI: Run 클릭
  → Worker: execution 요청
  → Project Runner Service: generated project runner CLI 호출
  → Generated Project: pytest/playwright 실행
  → Generated Project: results.json/artifacts 생성
  → Worker: results.json 파싱
  → SQLite: execution result 저장
  → GUI: 결과 표시
```

## 11.6 Result Export 시퀀스

```text
User
  → GUI: Export Results 클릭
  → Worker: export 요청
  → Result Export Service: results.json + cases.yaml 로드
  → Adapter: target별 API/write 수행
  → SQLite: export status 저장
  → GUI: export 결과 표시
```

---

## 12. 오류 처리 전략

## 12.1 Webwright 실행 오류

오류 유형:

```text
- API key 없음
- model config 오류
- Webwright 설치 오류
- Playwright browser 미설치
- start URL 접근 실패
- login 필요
- timeout
- Webwright가 final_script.py 생성 실패
- generated script 실행 실패
```

대응:

```text
- 오류 로그 표시
- 재시도 버튼 제공
- raw output folder 열기
- failed 상태 저장
- TC별 재실행 지원
```

## 12.2 Mapping 오류

오류 유형:

```text
- TC step보다 action이 너무 많음
- TC step과 action 매핑 불명확
- selector가 동적임
- assertion 부족
- 중복 action 존재
```

대응:

```text
- needs_review 상태 표시
- 사용자 수동 mapping 요구
- selector warning 표시
- action 삭제/수정 기능 제공
```

## 12.3 Project Execution 오류

오류 유형:

```text
- venv 없음
- requirements 미설치
- Playwright browser 미설치
- config/env 파일 없음
- 테스트 실패
- runner CLI 오류
```

대응:

```text
- Project Health Check 제공
- Install Dependencies 버튼 제공
- Run log 표시
- screenshot/trace 표시
- failed test rerun 제공
```

## 12.4 Result Export 오류

오류 유형:

```text
- TestRail token 오류
- testrail-clone API 오류
- Excel 파일 잠김
- Google Sheets 권한 오류
- mapping 누락
```

대응:

```text
- export 실패 항목별 표시
- 재시도 지원
- local results.json은 보존
- 원본 Excel 직접 수정 전 백업 생성
```

---

## 13. 보안 설계

## 13.1 API Key 보호

API key는 다음 파일에 저장하지 않는다.

```text
settings.json
project config
mappings/cases.yaml
generated project repo
logs
```

API key는 OS credential store에 저장한다.

## 13.2 로그 마스킹

로그 출력 시 다음 값을 마스킹한다.

```text
OpenAI API Key
Anthropic API Key
TestRail API Key
session cookie
auth token
password
```

## 13.3 generated project 보안

generated project에 비밀번호나 API key를 하드코딩하지 않는다.

환경별 설정은 다음처럼 분리한다.

```text
config/env.stg.json
.env.local
OS environment variables
credential store
```

---

## 14. 개발 단계 제안

## 14.1 MVP 1단계: Excel 기반 end-to-end

목표:

```text
Excel TC import
→ Webwright raw code 생성
→ raw code 확인
→ action 추출
→ mapping 확인
→ Playwright pytest project 생성
→ GUI에서 특정 테스트 실행
→ results.json 표시
```

범위:

```text
- Excel import
- automationKey 자동 생성
- Webwright CLI 실행
- final_script.py 저장
- action list 추출
- 수동 mapping 일부 지원
- 프로젝트 생성
- generated project 실행
- result summary 표시
```

제외:

```text
- TestRail 연동
- Google Sheets 연동
- 완전한 IDE 기능
- CI 연동
- 고급 selector 추천
```

---

## 14.2 MVP 2단계: Project IDE 강화

목표:

```text
생성된 자동화 프로젝트를 GUI에서 수정하고 실행 가능하게 한다.
```

범위:

```text
- 파일 트리
- Monaco Editor
- 저장
- 새 파일 생성
- 특정 TC 실행
- 로그 스트리밍
- screenshot/trace viewer
- failed test rerun
```

---

## 14.3 MVP 3단계: testrail-clone 연동

목표:

```text
testrail-clone에서 TC를 가져오고 실행 결과를 bulk upload한다.
```

범위:

```text
- testrail-clone API 설정
- TC import
- automationKey mapping
- result bulk upload
- coverage/report 연결
```

---

## 14.4 MVP 4단계: TestRail / Google Sheets / Excel write-back

목표:

```text
외부 TC 관리 도구와 결과 반영을 확장한다.
```

범위:

```text
- TestRail import/result update
- Google Sheets import/result update
- Excel result write-back
- source별 result mapping UI
```

---

## 15. 기술 선택 정리

## 15.1 권장 스택

```text
Desktop GUI:
- Electron
- React
- TypeScript
- Tailwind CSS
- Monaco Editor
- xterm.js

Local Worker:
- Python
- FastAPI
- Pydantic
- SQLite
- SQLModel 또는 SQLAlchemy

Automation:
- Webwright
- Playwright Python
- pytest

Generated Project:
- Python
- Playwright
- pytest
- pytest-html 또는 junitxml
- custom runner CLI

File/Integration:
- openpyxl
- Google Sheets API
- TestRail API
- testrail-clone API
```

## 15.2 Electron을 추천하는 이유

웹앱만으로는 다음 기능이 어렵다.

```text
- 로컬 Webwright 실행
- 로컬 Python venv 접근
- 파일시스템 프로젝트 생성
- subprocess 실행
- generated project 편집
- trace/screenshot 파일 열기
```

따라서 이 제품은 Electron이 적합하다.

---

## 16. 비목표

초기 버전에서 목표로 하지 않는 것:

```text
- 완전한 VS Code 대체
- Webwright 자체 수정
- 클라우드 기반 병렬 실행 플랫폼
- 완전 자동 POM 설계
- 사람이 전혀 개입하지 않는 100% 자동화 변환
- 모든 TestRail 커스텀 필드 완전 지원
- 모든 Excel 양식 자동 인식
```

이 도구의 핵심은 **자동화 초안 생성 + 구조화 + 실행 + 결과 반영을 연결하는 것**이다.

---

## 17. 주요 리스크와 대응

## 17.1 Webwright raw code 품질 리스크

문제:

```text
Webwright가 생성한 코드가 불안정한 selector, 과도한 wait, 불필요한 action을 포함할 수 있다.
```

대응:

```text
- Mapping & Review 화면 제공
- selector warning
- raw action 삭제/수정
- assertion 수동 추가
- generated code를 항상 사람이 수정 가능하게 생성
```

## 17.2 IDE 범위 과대화 리스크

문제:

```text
GUI를 완전한 IDE로 만들려 하면 범위가 너무 커진다.
```

대응:

```text
- 자동화 프로젝트 전용 미니 IDE로 제한
- 파일 편집, 저장, 실행, 결과 보기 중심
- refactor, debugger, extension ecosystem은 비목표
```

## 17.3 결과 export 신뢰성 리스크

문제:

```text
잘못된 mapping으로 다른 TC에 결과가 입력될 수 있다.
```

대응:

```text
- automationKey 필수화
- export 전 preview 제공
- Excel write-back 전 백업 생성
- export log 저장
- sourceCaseId와 automationKey 동시 검증
```

## 17.4 로컬 환경 차이 리스크

문제:

```text
Windows, WSL, macOS, Linux 환경마다 Webwright/Playwright 실행 방식이 다르다.
```

대응:

```text
- executionMode 설정: native / wsl
- setup wizard 제공
- health check 제공
- install dependencies 버튼 제공
- smoke test 제공
```

---

## 18. 최종 아키텍처 요약

최종 구조는 다음과 같다.

```text
TC Source
  ├─ TestRail
  ├─ testrail-clone
  ├─ Excel
  └─ Google Sheets
        ↓
Case Import Service
        ↓
Normalized Test Case + automationKey
        ↓
Prompt Builder
        ↓
Webwright CLI Adapter
        ↓
Raw Webwright Artifacts
  ├─ final_script.py
  ├─ trajectory.json
  ├─ screenshots
  └─ logs
        ↓
Action Extraction Service
        ↓
Mapping & Review
        ↓
Structuring Service
        ↓
Project Generator Service
        ↓
Generated Automation Project
  ├─ tests
  ├─ pages
  ├─ flows
  ├─ fixtures
  ├─ runner
  ├─ mappings
  └─ artifacts
        ↓
Project Runner Service
        ↓
Execution Results
        ↓
Result Export Service
        ↓
TC Source Result Update
```

이 구조의 핵심 판단은 다음과 같다.

```text
1. TC가 기준이다.
2. Webwright는 raw code 생성 엔진이다.
3. raw code는 최종 산출물이 아니다.
4. mapping/review 단계가 필수다.
5. generated project가 실제 자동화 실행을 소유한다.
6. GUI는 생성·편집·실행·결과 반영을 오케스트레이션한다.
7. 결과 반영은 automationKey를 기준으로 수행한다.
8. generated project는 GUI 없이도 CI에서 독립 실행 가능해야 한다.
```

---

## 19. 권장 MVP 결론

첫 번째 버전은 다음 흐름을 완성하는 데 집중한다.

```text
Excel TC import
  ↓
TC별 Webwright raw code 생성
  ↓
raw action 추출
  ↓
TC-action mapping review
  ↓
structured Playwright pytest project 생성
  ↓
GUI에서 generated project 실행
  ↓
results.json 표시
```

이 흐름이 안정화된 뒤에 다음을 추가한다.

```text
testrail-clone 연동
  ↓
result bulk upload
  ↓
Project IDE 강화
  ↓
TestRail / Google Sheets / Excel write-back
```

이 순서가 가장 현실적이다.

처음부터 TestRail, Google Sheets, 완전한 IDE, 고급 결과 동기화까지 모두 넣으면 제품 범위가 지나치게 커진다.

따라서 초기 목표는 **Excel 기반 TC → Webwright → 구조화 프로젝트 생성 → GUI 실행**으로 잡는 것이 좋다.

