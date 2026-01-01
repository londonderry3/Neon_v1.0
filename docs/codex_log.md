# Codex Interaction Log
> 목적: AI(Codex)를 활용한 코드 변경의 **의도, 판단, 결과**를 기록한다.
> 원칙: AI 출력이 아니라 **내가 내린 설계 결정**을 남긴다.

---

## [YYYY-MM-DD] Change ID: CXX
### Target
- File(s):
  - app.py
  - collector.py
- Scope:
  - refactor / feature / cleanup / performance / experiment

---

### 1. Context (Why I touched this)
> ❗ 이 섹션이 가장 중요함

- 현재 문제:
  - (예: collector.py에 daily/cum 로직이 섞여 있음)
- 제약 조건:
  - (예: API response 변경 금지)
- 이번 변경의 목표:
  - (예: 가독성 개선, signal 확장 대비)

---

### 2. Prompt I Gave to Codex (Raw)
> ✅ **내가 실제로 입력한 프롬프트를 그대로 복붙**
> ❌ Codex가 정제해준 문장 X

```text
collector.py에서
- 데이터 수집 로직은 유지
- daily / cumulative 계산을 함수로 분리
- 기존 API 응답 구조는 변경하지 말 것
- 최소 diff로 리팩토링 제안해줘