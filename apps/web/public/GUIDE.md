# OpenCrab 웹 UI 사용 가이드

## 🌐 웹 UI 화면 구성

```
┌────────────────────────────────────────────────────────────┐
│  [파일 탐색기]  │      [그래프 뷰]      │  [상세/컨트롤]  │
│                 │                       │                  │
│  - 노드 목록    │  - 시각화 그래프      │  - 선택 노드     │
│  - 카테고리     │  - 검색 바            │  - 그래프 설정   │
│  - API 키       │  - 줌/드래그          │  - 인제스트      │
└────────────────────────────────────────────────────────────┘
```

---

## 🔍 검색 기능 사용법

### 1. **그래프 뷰 검색**
상단 검색창에 키워드 입력:
- **노드 ID** 검색: `acli_jira_workitem`
- **이름** 검색: `ELERA`, `GitLab`, `RPA`
- **카테고리** 검색: `automation`, `security`

👉 **결과**: 일치하는 노드는 밝게, 나머지는 희미하게 표시

### 2. **왼쪽 패널 필터**
- 노드 목록을 스크롤하며 탐색
- 클릭하면 그래프에서 강조 표시

---

## 🎯 그래프 탐색 방법

### 기본 조작
- **줌**: 마우스 휠
- **이동**: 드래그 (빈 공간)
- **노드 이동**: 노드를 드래그
- **노드 클릭**: 상세 정보 표시

### 노드 색상 의미
- 🟡 **Landscape** (#5ea85b) - 조경, 정원 관련
- 🟠 **AI** (#e38b2c) - AI, 자동화 관련
- 🟣 **Alex** (#d97ab5) - OpenCrab, CrabHarness 등
- ⚪ **Fallback** (#7c6f64) - 기타

---

## 📊 실제 활용 예시

### 예시 1: "ELERA POS는 어떤 OS 위에서 돌아가?"

1. 검색창에 `ELERA` 입력
2. `elera_platform` 노드 클릭
3. 연결된 노드들 확인:
   - `toshiba_tgcs_org` (소유 조직)
   - `toshiba_offerings_page_text` (관련 문서)

### 예시 2: "acli로 work item 만드는 명령은?"

1. 검색창에 `acli` 또는 `workitem` 입력
2. `acli_jira_workitem_link_create` 노드 찾기
3. 오른쪽 패널에서 상세 정보 확인:
   - URL: 명령어 문서 링크
   - 설명: Create links between work items

### 예시 3: "GitLab 파이프라인 구조는?"

1. 검색창에 `pipeline` 입력
2. `parent_pipeline`, `child_pipeline` 노드 찾기
3. 관계 확인:
   - parent → child (triggers)
   - stages: build, test, deploy

### 예시 4: "RPA 관련 문서는?"

1. 검색창에 `RPA` 또는 `automation` 입력
2. `concept_automation` 노드 찾기
3. 연결된 문서들 확인:
   - `doc_sw_RPA_Workflow_...` (3개 문서)

---

## 🎛️ 그래프 컨트롤 (오른쪽 패널)

### 시각화 설정
- **Node Size**: 노드 크기 조절
- **Link Strength**: 연결선 강도
- **Center Force**: 중심 끌어당기는 힘
- **Repel Force**: 노드 간 밀어내는 힘

### Hidden Spaces
체크박스로 특정 공간(space) 숨기기:
- ☐ subject (주체)
- ☐ resource (자원)
- ☐ concept (개념)
- ☐ evidence (증거)
- ☐ outcome (결과)
- ☐ lever (레버)

---

## 💡 고급 활용법

### 1. **관계 추적**
노드 클릭 → 오른쪽 패널 → 연결된 노드 목록 확인

### 2. **카테고리별 탐색**
- 왼쪽 패널에서 space별 필터링
- 색상으로 테마별 그룹 파악

### 3. **영향 범위 분석**
특정 노드에서 시작해서 연결된 모든 노드 추적
- 예: ELERA → 관련 조직 → 제품 → 문서

---

## 🔧 데이터 업데이트

새로운 팩을 설치하거나 데이터가 변경되면:

```bash
"그래프 데이터를 다시 export 해줘"
```

자동으로 `nodes.json`, `edges.json` 재생성 후 새로고침

---

## 📦 현재 설치된 팩

### 1. **toshiba-day5-dev-pack** (510 노드, 593 엣지)
- Atlassian acli 명령어
- GitLab CI/CD 파이프라인
- ELERA 플랫폼 정보
- Jira/Confluence 워크플로우

**샘플 검색어:**
- `acli jira`
- `GitLab pipeline`
- `ELERA`
- `merge train`

### 2. **my-downloads-pack** (8 노드, 7 엣지)
- Downloads 폴더 문서
- 카테고리: Automation, Security, Development

**샘플 검색어:**
- `RPA`
- `automation`
- `security`
- `github recovery`

---

## 🚀 Quick Start

1. **http://localhost:3000** 열기
2. 상단 검색창에 관심 키워드 입력
3. 노드 클릭해서 상세 정보 확인
4. 연결된 노드들을 따라가며 탐색
5. 오른쪽 설정으로 시각화 조정

---

## ❓ FAQ

**Q: 그래프가 너무 복잡해요**
A: Hidden Spaces에서 불필요한 space 체크 또는 검색창으로 필터링

**Q: 노드가 겹쳐 보여요**
A: Repel Force 값을 높이면 노드들이 더 멀리 배치됩니다

**Q: 특정 문서의 원본을 보고 싶어요**
A: 노드 클릭 → 오른쪽 패널에서 `path` 또는 `url` 속성 확인

**Q: 새로운 문서를 추가하려면?**
A: "내 Downloads 폴더를 다시 팩으로 만들어줘" 요청

---

## 📚 더 알아보기

- OpenCrab Pack v1 포맷: `C:\Users\amore\OpenCrab\docs\opencrab-pack-v1.md`
- MetaOntology 9-Space: `concept`, `resource`, `subject`, `evidence`, `claim`, `outcome`, `lever`, `policy`, `community`
