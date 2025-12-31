# 💎 Jemi-System Project Context (V 5.0)
*마지막 동기화: 2025-12-20*

## 1. 시스템 개요
- **컨셉:** 정량적 하드 로직(수급/가격) + 제미(Jemi)의 정성적 판단을 결합한 하이브리드 스윙 매매 시스템.
- **아키텍처:** Flask 기반의 자체 관리 IDE(v5.0)를 통해 설계(Docs)와 구현(Python)을 동기화함.
- **핵심 철학:** 설계자가 `docs/` 내 마크다운을 수정하면 서버가 이를 파싱하여 로직에 실시간 반영.

## 2. 현재 아키텍처 R&R
- **Management Layer (HTML/Flask):** `manage_v5.py`를 통해 웹 브라우저에서 `docs/` 파일을 직접 편집/저장.
- **Execution Layer (Python):** `main.py`를 정점으로 `core/`, `ai/`, `data/` 모듈로 계층화.
- **Configuration (Docs):** 모든 가중치와 프롬프트는 `docs/*.md`에 중앙 집중화.

## 3. 진행 상황 (Milestones)
- [x] **Phase 0:** 계층형 탭 및 Mermaid 플로우차트 대시보드 구축 완료.
- [x] **Phase 1-A:** Flask 기반 실시간 에디터(Save 기능 포함) 구현 완료.
- [x] **Phase 1-B:** M-01(수급 선행성) 수치 분석 스켈레톤 코드 작성 완료.
- [ ] **Phase 2:** `ai/jemi_news.py` 개발 및 Google Gemini API 연동 (진행 예정).
- [ ] **Phase 3:** 텔레그램 인터럽트 인터페이스 및 VPS 배포 설계.

## 4. 로직 핵심 변수
- **M-01 (Supply):** 외인(0.6), 기관(0.4) 가중치 합산 / 최근 데이터 가중 평균(0.2, 0.3, 0.5) 적용.
- **Jemi Prompt:** 전문가 페르소나 부여 및 뉴스 데이터의 수치화(-10~10) 프로토콜 설계 중.

## 5. 다음 대화 재개 시 가이드
> "이전 세션에서 Flask IDE 기반 v5.0까지 구축했어. `docs/project_context.md`를 읽고 Phase 2인 AI 추론 모듈 연결부터 도와줘."