# Meta Codex Crawler — 구조 설계 플랜

- Date: 2026-04-11
- Status: draft (plan mode, no code yet)
- Scope: CrabHarness를 SOEAK-전용에서 **목적물(target_object) 기반 메타 수집 플랫폼**으로 일반화. Claude Code 플래너 + Codex 플러그인 실행기 체계 정립. loopy-era-trend-harvester의 수확 파이프라인을 CrabHarness의 상위 워크플로우로 흡수.

---

## 0. 입력 소스 정리

- **Notion 가이드**: https://www.notion.so/OpenCrab-CrabHarness-Codex-Crawler-33eb275eefd0811ea657d35c2b6e8271 (미열람, 후속 세션에서 확인 필요)
- **self-evolving-analysis**: https://hugh-kim.space/self-evolving-analysis.html (철학 소스, 후속 세션에서 확인)
- **loopy-era-trend-harvester**: `/loopy-era-trend-harvester.zip` → 수확 파이프라인 blueprint (SKILL.md 전체 분석 완료)
- **기존 워커**: `soeak-detail-crawler.ts` (940줄, Playwright 기반 G2B 상세 크롤러)
- **OpenCrab**: `C:\Users\daewooenc\workspace\OpenCrab` (온톨로지/정책 기반, 참조 전용)

---

## 1. 현재 상태 (Codex가 빌드해놓은 것)

### 1.1 작동하는 부분
- `crabharness/` Python 제어평면: CLI (catalog/plan/delegate/run/doctor/schema/promotion-stub)
- 5개 스키마: mission, delegation-job, artifact-bundle, validation-report, promotion-package
- SOEAK 워커 end-to-end 파이프라인: plan → delegate → subprocess → collect_bundle → validate → promotion 생성
- Playwright, sqlite 테이블 생성, progress/error 로그 저장 모두 동작
- `run_mission()` 실행 시 `artifacts/runs/<mission>/<run_id>/` 하위에 9개 산출물 저장

### 1.2 SOEAK-전용 하드코딩 지점 (일반화 대상)
| 위치 | 하드코딩 내용 |
|---|---|
| `delegation.py::_job_args` | `bid_no`, `bid_ntce_ord`, `division`, `include_processing` 등 CLI 플래그 매핑 |
| `adapters/soeak.py` | `required_source_tables = [analysis_soeak_raw, procurement_listings, award_results]` (실제 DB와 불일치) |
| `adapters/soeak.py` | `analysis_soeak_cases/bidders/reserve_prices` SQL 직접 조회 |
| `runtime.py::_collect_bundle` | `if job.worker_id == "codex.soeak.detail"` 분기 (워커마다 if 추가 필요) |
| `runtime.py::_validate_bundle` | 동일 분기 구조 |
| `registry.py` | 소스코드 리스트 하드코딩 (플러그인 미지원) |
| `models.py::MissionSpec` | `target: dict` 자유 형식이지만 사실상 SOEAK 필드 기대 |
| 샘플 미션 `soeak-bidcase.json` | `bid_no=202604110001` 더미 (실데이터 없음) |

### 1.3 해결된 이슈 (시간순)
1. `no such table: analysis_soeak_raw` → 새 스키마로 전환
2. Puppeteer frame timing → Playwright 교체
3. Playwright 브라우저 미설치 → install
4. 현재 최신 run: 크래시 없음, 단 타겟 bid가 더미라 0 rows

---

## 2. 목표 아키텍처

### 2.1 원칙
1. **목적물 우선(target-object first)**: 미션은 특정 ID가 아닌 "무엇을 알고 싶은가"로 시작
2. **워커는 플러그인**: 각 워커는 자체 manifest + 자체 collector/validator 모듈을 등록. 코어는 dispatch만.
3. **Claude = 플래너·검증자**, **Codex = 실행자**: 수집/스크래핑/파싱처럼 토큰 많이 쓰는 작업은 Codex 플러그인에 위임
4. **HARD 게이트**: loopy 스타일로 validation을 단순 schema match가 아닌 "목표 관점 충족도 + 재현가능성" 점수로
5. **Dedupe across runs**: 같은 URL/ID 중복 수집 방지 seen-index
6. **수집→분석→승격** 파이프라인 loopy 5단계와 일치시킴

### 2.2 컴포넌트 다이어그램
```
┌────────────────────────────────────────────────────────────┐
│  Claude Code (Planner)                                     │
│  - 미션 해석 → collection plan 분해                        │
│  - 워커 선택 (registry scoring)                             │
│  - 산출물 semantic validate                                 │
│  - 승격 결정                                                │
└──────────┬─────────────────────────────┬───────────────────┘
           │                             │
           ▼                             ▼
┌─────────────────────────┐   ┌─────────────────────────────┐
│  Codex Plugin Runtime   │   │  OpenCrab (read-only ref)  │
│  (delegation target)    │   │  - ontology / policy        │
│  - worker subprocess     │   │  - 승격 대상 스키마         │
│  - artifact emit         │   └─────────────────────────────┘
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│  Workers (plugin dir)                                    │
│  codex_workers/                                          │
│  ├─ soeak/                  ← existing, to be refactored │
│  │  ├─ worker.manifest.json                              │
│  │  ├─ adapter.py           (collector + validator)      │
│  │  └─ crawler.ts                                        │
│  ├─ github_trending/        ← new (loopy Phase 1-A)      │
│  ├─ guru_github/            ← new (loopy Phase 1-A')     │
│  ├─ rss_feed/               ← new (loopy Phase 1-C)      │
│  └─ web_generic/            ← new (meta crawl fallback)  │
└──────────────────────────────────────────────────────────┘
```

### 2.3 MissionSpec 확장
```yaml
mission_id: str
workspace_id: str
objective: str                          # free text
target_object: str                      # BidCase, TrendSignal, RepoInsight, ...
target_spec: dict                       # 워커가 해석, 코어는 passthrough
questions: list[str]                    # LLM validator가 채점
collection_mode: targeted | exploratory | refresh | harvest   # + harvest 추가
required_evidence: list[str]
success_criteria:
  min_artifacts: int
  required_fields: list[str]
  completeness_threshold: float
  semantic_questions: list[str]         # NEW — LLM 점수화 대상
  min_semantic_score: float             # NEW — 0~1
constraints:
  max_jobs: int
  concurrency, delay_ms, dry_run
  allowed_sources: list[str]
  dedupe_key: str | null                # NEW — seen-index 키
promotion_policy: manual_review | auto_if_valid | disabled
```

### 2.4 Worker Manifest 확장 (JSON)
```json
{
  "worker_id": "codex.soeak.detail",
  "job_type": "g2b_bid_detail_crawl",
  "supported_targets": ["BidCase", "ProcurementNotice"],
  "tags": ["procurement", "g2b", "soeak"],
  "command": ["npm", "--prefix", "./worker_runtime", "run", "worker:soeak", "--"],
  "arg_schema": {
    "bid_no":       {"flag": "--bid-no",       "required": false},
    "bid_ntce_ord": {"flag": "--bid-ord",      "required": false, "default": "000"},
    "division":     {"flag": "--division",     "required": false},
    "limit":        {"flag": "--limit",        "from_option": true},
    "concurrency":  {"flag": "--concurrency",  "from_option": true},
    "delay_ms":     {"flag": "--delay-ms",     "from_option": true},
    "dry_run":      {"flag": "--dry-run",      "from_option": true, "type": "bool"}
  },
  "adapter_module": "codex_workers.soeak.adapter",
  "artifact_types": [...],
  "validation_checks": [...],
  "opencrab_mapping": {...}
}
```
→ `delegation.py::_job_args`에서 if-else 제거, `arg_schema` 기반 자동 빌드.

### 2.5 Adapter Plugin 인터페이스
```python
# codex_workers/<name>/adapter.py
def collect_bundle(root_dir, mission, job, run_id, progress_path, error_log_path) -> ArtifactBundle: ...
def validate_bundle(bundle, mission) -> ValidationReport: ...
```
- `registry.py`가 manifest를 스캔해서 `adapter_module`을 동적 import
- `runtime.py::_collect_bundle / _validate_bundle`의 if-체인 제거 → registry.resolve(worker_id).adapter

### 2.6 Loopy 수확 파이프라인 흡수
loopy의 phase → CrabHarness 단계 매핑:
| loopy phase | CrabHarness 위치 | 구현 방식 |
|---|---|---|
| Phase 0 guard (lockfile/cooldown) | runtime 진입 | `_workspace/.lock`, cooldown via CronCreate |
| Phase 0.5 dedup | runtime 진입 전 | `_workspace/.seen.json` + `dedupe_key` |
| Phase 1 scan | worker subprocess | 기존 delegation 그대로 |
| Phase 2 analyze | validator 확장 | LLM semantic score (Claude가 Phase로 호출) |
| Phase 3 baseline | harness-report 연동 | 별도 skill reuse |
| Phase 3.5 autoresearch | promotion gate | `keep/discard` verdict 저장 |
| Phase 4 apply | promotion builder | 기존 `promotion.py` 확장 |
| Phase 5 report | 통지 | Discord + Telegram (현 세션 Discord 우선) |
| Phase 6 html log | 선택 | 우선순위 낮음 |

### 2.7 Codex 플러그인 위임 형식
현재는 `build_codex_payload()`가 "command + args + brief" 딕셔너리만 생성 → **실제 Codex 플러그인을 호출하지 않음**. 목표:
- 옵션 A: `codex:rescue` skill로 위임 (대형 크롤링 1회성)
- 옵션 B: 독립 subprocess (현재 방식, 빠름)
- 옵션 C: MCP tool로 노출하고 Claude가 도구 호출로 트리거

초기엔 B (현재 방식 유지), 나중에 A/C를 선택적으로 추가. Payload는 양쪽 다 호환되게 `delegate_target: "subprocess" | "codex_plugin"` 필드 추가.

---

## 3. 마이그레이션 단계 (순서)

### Step 1 — 하드코딩 제거 (core 일반화) — **우선**
1. `registry.py`: 정적 리스트 → `codex_workers/*/worker.manifest.json` glob 스캔
2. `worker.manifest.json` 스키마에 `arg_schema`, `adapter_module` 추가
3. `delegation.py::_job_args` 삭제, `arg_schema` 기반 빌더로 교체
4. `runtime.py::_collect_bundle / _validate_bundle` dispatch를 `registry.resolve(worker_id).adapter` 로 교체
5. SOEAK 어댑터를 `crabharness/adapters/soeak.py` → `codex_workers/soeak/adapter.py` 이동
6. `crabharness/adapters/` 폴더는 ABC/프로토콜만 남김
7. `missing_source_tables` 체크 삭제 또는 per-worker 정책으로 이동

### Step 2 — MissionSpec 확장
8. `semantic_questions`, `min_semantic_score`, `dedupe_key` 필드 추가
9. 샘플 미션을 "실제 존재하는 G2B 입찰 검색 → 수집" 형식으로 교체 (soeak 워커 첫 실사용)

### Step 3 — Dedupe / seen-index
10. `_workspace/.seen.json` 스키마 구현 (loopy 스타일)
11. `is_seen/mark_seen` helper를 `crabharness/dedupe.py`로 추가
12. runtime 진입 시 dedupe 체크 → 기존 bundle 재사용 옵션

### Step 4 — Semantic validator
13. `crabharness/semantic.py`: mission.semantic_questions 기반 Claude 호출로 점수화
14. `ValidationReport`에 `semantic_score`, `question_verdicts` 필드 추가
15. autoresearch 스타일 `keep/discard/crash` verdict 저장 → `promotion.py` 게이트

### Step 5 — 새 워커 추가 (loopy Phase 1 구현)
16. `codex_workers/github_trending/` — WebFetch + jsonl 저장
17. `codex_workers/guru_github/` — GitHub API scanner
18. `codex_workers/rss_feed/` — generic RSS
19. 각 워커는 Step 1~4의 인터페이스 그대로 사용

### Step 6 — 수확 미션 템플릿
20. `missions/templates/trend-harvest.json` — loopy 스킬의 1회 수확을 CrabHarness 미션으로
21. `/loop 6h python -m crabharness run missions/templates/trend-harvest.json` 로 주기 실행

### Step 7 — 승격 파이프라인
22. `promotion.py` 확장: semantic_score + autoresearch verdict → OpenCrab node/edge 생성
23. 성공 시 Discord/Telegram 통지 메시지 포맷

---

## 4. 비범위 (이번 플랜에서 제외)
- OpenCrab-saas 연동 (사용자 명시 제외)
- HTML 로그 사이트 생성 (Phase 6)
- `vercel.ts` / Vercel 배포 관련 (저장소가 Python 패키지)
- `.claude/skills/` 으로의 스킬화 (CrabHarness는 독립 CLI)

## 5. 리스크 & 결정 포인트
- **Q1**: Codex 플러그인 위임은 subprocess 유지 vs MCP tool? → 초기 subprocess, 후속에서 MCP 고려
- **Q2**: Semantic validator의 LLM 호출 비용 → loopy처럼 Phase 2만 LLM, Phase 3.5는 HARD exit code만
- **Q3**: loopy의 harness-report 점수가 CrabHarness엔 없음 → 대체 메트릭으로 "mission completeness + semantic_score" 조합 사용
- **Q4**: seen-index가 거대해질 경우 → 주간 압축 or sqlite 이전

## 6. 성공 기준 (플랜 검증용)
- 목표 미션 1건이 **하드코딩 없이** SOEAK 워커로 E2E pass
- 새 워커 1종 (github_trending 예정)을 core 수정 없이 manifest+adapter만으로 등록 가능
- seen-index 적중률 > 0 (동일 미션 2회차에서 dedupe 동작 증거)
- semantic validator가 mission.questions를 채점 리포트로 반환

---

## 7. 다음 액션 (사용자 승인 후 진행)
1. 이 플랜 Discord 요약 전송
2. 사용자 승인 후 Step 1부터 구현 (하드코딩 제거가 blocking)
3. Step 1 완료 시점에 loopy-era-trend-harvester 소스 재검토 → Step 5 워커 설계 상세화
