---
name: exploration-prompt-generator
description: 시스템 데이터를 컨텍스트로 포함한 외부 Claude 탐색용 프롬프트 생성기. 종목 탐색, 포트폴리오 점검, thesis 반대 논거 탐색용.
---

이 스킬은 사용자가 시스템 밖의 Claude와 자유롭게 탐색 대화를 할 때 붙여넣을 프롬프트를 생성합니다.

## 탐색 유형

### 1. 종목 탐색 (discovery)
현재 포트폴리오와 관심 목록을 컨텍스트로 포함하여, 새로운 투자 아이디어를 외부 Claude와 자유롭게 탐색합니다.

**포함 내용:**
- 현재 포트폴리오 종목 (stock_type + 핵심 가정 요약)
- 관심 목록 종목
- 탐색 방향 가이드 (6가지 렌즈 중 선택 또는 혼합)

**탐색 후:**
시스템으로 돌아와 관심 종목을 추가하고, ConversationImport(discovery)로 핵심 인사이트를 기록합니다.

### 2. 포트폴리오 점검 (portfolio_review)
현재 포트폴리오 상세 현황을 컨텍스트로 포함하여, 전략적 시각에서 점검합니다.

**포함 내용:**
- 종목별 보유 현황 (단가, 평가손익)
- thesis 상태 및 stock_type
- 핵심 가정 요약

**탐색 후:**
ConversationImport(portfolio_review)로 주요 인사이트를 기록합니다.

### 3. 반대 논거 탐색 (thesis_challenge)
특정 종목의 현재 seed_memo 또는 thesis를 컨텍스트로 포함하여, 반대 논거를 집중 탐색합니다.

**포함 내용:**
- 현재 thesis 요약
- 핵심 가정
- "이 논리의 어느 부분이 틀릴 수 있는가?" 질문

**탐색 후:**
강화된 seed_memo로 thesis를 재생성하거나, ConversationImport(thesis_challenge)로 기록합니다.

### 4. 종목 집중 분석 (deep_analysis)
특정 종목의 보고서 데이터를 컨텍스트로 포함하여, 투자 관점 수립을 위한 심층 탐색을 합니다.

**포함 내용:**
- 종목 기본 정보
- 보고서 주요 내용 (있는 경우)
- "왜 지금 사고 싶은가?" 초기 관점

**탐색 후:**
seed_memo + exploration_note를 작성하여 thesis 생성에 활용합니다.

## 구현 방식

이 스킬의 실제 프롬프트 생성은 `/api/reports/explore-prompt?type={type}` 엔드포인트에서 DB 데이터를 조회하여 수행합니다. LLM 호출 없이 텍스트 빌더로 구현됩니다.

사용자가 "프롬프트 복사" 버튼을 클릭하면 해당 엔드포인트를 호출하고, 반환된 텍스트를 클립보드에 복사합니다.
