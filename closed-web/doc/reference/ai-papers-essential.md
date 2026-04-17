---
title: ai-papers-essential
kind: reference
project: openakashic
status: active
confidence: high
tags: []
related: []
visibility: private
created_by: aaron
owner: aaron
publication_status: rejected
updated_at: 2026-04-15T09:47:59Z
created_at: 2026-04-15T02:08:44Z
publication_requested_at: 2026-04-15T02:09:05Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:59Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
---

## Summary
AI / ML 필수 논문 모음. Transformer 시대 이후 현재까지 실무·연구 모두에서 반드시 알아야 하는 논문을 연도순으로 정리. 원문 링크 + 핵심 기여 + 실무 영향 3가지 기준으로 요약.

## Sources
- arXiv.org 원문
- Sebastian Raschka "LLM Research Papers 2024/2025 List"
- Hugging Face Papers
- Papers With Code

---

## 1. 기반 아키텍처

### Attention Is All You Need (2017)
- **저자**: Vaswani et al. (Google Brain)
- **arXiv**: [1706.03762](https://arxiv.org/abs/1706.03762)
- **핵심 기여**: RNN·CNN 없이 Self-Attention만으로 seq2seq. Multi-Head Attention, Positional Encoding. 병렬 학습으로 GPU 효율 극대화.
- **수식 핵심**: `Attention(Q,K,V) = softmax(QKᵀ/√d_k)V`
- **실무 영향**: GPT, BERT, T5, LLaMA… 모든 현대 LLM의 조상. 이 논문 없이 현재 AI 붐은 없었음.

### BERT: Pre-training of Deep Bidirectional Transformers (2018)
- **저자**: Devlin et al. (Google)
- **arXiv**: [1810.04805](https://arxiv.org/abs/1810.04805)
- **핵심 기여**: MLM(Masked Language Modeling) + NSP로 양방향 Transformer 사전학습. 11개 NLP 벤치마크 SOTA.
- **실무 영향**: Fine-tuning 패러다임 확립. 이후 모든 NLP 파이프라인의 표준.

### GPT-3: Language Models are Few-Shot Learners (2020)
- **저자**: Brown et al. (OpenAI)
- **arXiv**: [2005.14165](https://arxiv.org/abs/2005.14165)
- **핵심 기여**: 1750억 파라미터. In-context learning(few-shot/zero-shot)으로 태스크별 파인튜닝 없이 다목적 추론.
- **실무 영향**: Prompt engineering의 시작. API 기반 AI 제품 시대 개막.

---

## 2. 정렬·지시 따르기

### InstructGPT: Training language models to follow instructions with human feedback (2022)
- **저자**: Ouyang et al. (OpenAI)
- **arXiv**: [2203.02155](https://arxiv.org/abs/2203.02155)
- **핵심 기여**: SFT + RLHF(PPO). 인간 피드백으로 "도움되고·무해하고·정직한" 모델 훈련.
- **실무 영향**: ChatGPT의 직접 기원. RLHF 파이프라인 산업 표준화.

### Constitutional AI: Harmlessness from AI Feedback (2022)
- **저자**: Bai et al. (Anthropic)
- **arXiv**: [2212.08073](https://arxiv.org/abs/2212.08073)
- **핵심 기여**: RLAIF — 인간 레이블 없이 AI가 자체 원칙(Constitution)으로 피드백 생성. CAI.
- **실무 영향**: Claude 시리즈의 훈련 방법론. 대규모 RLHF 비용 절감.

---

## 3. 추론·프롬프팅

### Chain-of-Thought Prompting Elicits Reasoning in LLMs (2022)
- **저자**: Wei et al. (Google)
- **arXiv**: [2201.11903](https://arxiv.org/abs/2201.11903)
- **핵심 기여**: "Let's think step by step" 한 문장으로 수학·논리 문제 정답률 수직 상승. CoT.
- **실무 영향**: 복잡한 추론 태스크에서 CoT는 기본 레시피.

### ReAct: Synergizing Reasoning and Acting in Language Models (2022)
- **저자**: Yao et al. (Princeton/Google)
- **arXiv**: [2210.03629](https://arxiv.org/abs/2210.03629)
- **핵심 기여**: Thought → Action → Observation 루프. 도구(검색·계산기)와 추론을 인터리브.
- **실무 영향**: 에이전트 루프의 원형. LangChain Agent, Claude tool_use의 개념적 기반.

### Tree of Thoughts: Deliberate Problem Solving with LLMs (2023)
- **저자**: Yao et al. (Princeton)
- **NeurIPS 2023**: [PDF](https://proceedings.neurips.cc/paper_files/paper/2023/file/271db9922b8d1f4dd7aaef84ed5ac703-Paper-Conference.pdf)
- **핵심 기여**: CoT(선형)를 트리 구조로 확장. 중간 추론 단계를 BFS/DFS로 탐색·백트래킹.
- **실무 영향**: 코드 생성·수학 증명 등 탐색이 필요한 문제에서 성능 ↑. 계산 비용이 높아 실용화 제한적.

### Self-Consistency Improves CoT Reasoning (2022)
- **저자**: Wang et al. (Google)
- **arXiv**: [2203.11171](https://arxiv.org/abs/2203.11171)
- **핵심 기여**: 동일 문제를 여러 번 샘플링 후 다수결(Majority Voting). Greedy 보다 일관성 ↑.
- **실무 영향**: 고비용이지만 정확도가 중요한 추론에서 앙상블 대안.

---

## 4. 효율·아키텍처 개선

### LLaMA: Open and Efficient Foundation LMs (2023)
- **저자**: Touvron et al. (Meta)
- **arXiv**: [2302.13971](https://arxiv.org/abs/2302.13971)
- **핵심 기여**: GPT-3 수준 성능을 훨씬 작은 모델로. 오픈 가중치. RMSNorm, SwiGLU, RoPE.
- **실무 영향**: 오픈소스 LLM 생태계 폭발. Llama 3.x까지 진화. 로컬 추론 대중화.

### Mistral 7B (2023)
- **저자**: Jiang et al. (Mistral AI)
- **arXiv**: [2310.06825](https://arxiv.org/abs/2310.06825)
- **핵심 기여**: GQA(Grouped Query Attention) + Sliding Window Attention. 7B로 Llama 2 13B 능가.
- **실무 영향**: 소형 모델 고성능화의 이정표.

### FlashAttention-2 (2023)
- **저자**: Dao et al. (Stanford)
- **arXiv**: [2307.08691](https://arxiv.org/abs/2307.08691)
- **핵심 기여**: IO-aware 어텐션 구현. 시퀀스 병렬화. 학습 속도 2~4배 ↑.
- **실무 영향**: 긴 컨텍스트(128k+) 처리 가능하게 만든 핵심 기술.

---

## 5. 에이전트·멀티에이전트

### Toolformer: Language Models Can Teach Themselves to Use Tools (2023)
- **저자**: Schick et al. (Meta)
- **arXiv**: [2302.04761](https://arxiv.org/abs/2302.04761)
- **핵심 기여**: 자기지도 방식으로 도구 호출 학습(calculator, search, calendar). 파인튜닝 없이.
- **실무 영향**: Function calling / tool use의 학술적 기반.

### MetaGPT: Meta Programming for Multi-Agent Collaboration (2023)
- **저자**: Hong et al.
- **arXiv**: [2308.00352](https://arxiv.org/abs/2308.00352)
- **핵심 기여**: 소프트웨어 개발팀을 다중 에이전트로 시뮬레이션. 역할(PM/아키텍트/개발/QA) 분리.
- **실무 영향**: 멀티에이전트 프레임워크 설계 참조.

### AgentBench: Evaluating LLMs as Agents (2023)
- **저자**: Liu et al. (Tsinghua)
- **arXiv**: [2308.03688](https://arxiv.org/abs/2308.03688)
- **핵심 기여**: 8개 실제 환경(OS, DB, 웹, 게임)에서 LLM 에이전트 평가 벤치마크.
- **실무 영향**: 에이전트 평가 표준화 기여.

### Building Effective Agents (2024)
- **저자**: Anthropic
- **URL**: [anthropic.com/engineering/building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)
- **핵심 기여**: "워크플로우 vs 에이전트" 명확 구분. 5개 설계 패턴(체이닝·라우팅·병렬화·오케스트레이션·평가). 실제 배포 경험 기반.
- **실무 영향**: Anthropic 공식 에이전트 설계 가이드. 현재 가장 실용적인 레퍼런스.

---

## 6. 추론 특화 (2025 최신)

### DeepSeek-R1: Incentivizing Reasoning via RL (2025)
- **저자**: DeepSeek AI
- **arXiv**: [2501.12948](https://arxiv.org/abs/2501.12948)
- **핵심 기여**: SFT 없이 순수 RL(GRPO)로 추론 능력 창발. 오픈 가중치. GPT-o1 수준.
- **수치**: AIME 2024 79.8%, MATH 97.3%, Codeforces 96.3 퍼센타일.
- **실무 영향**: RLHF 없는 추론 훈련 가능성 증명. 오픈소스 추론 모델 시대 개막.

### From LLM Reasoning to Autonomous AI Agents (2025)
- **arXiv**: [2504.19678](https://arxiv.org/abs/2504.19678)
- **핵심 기여**: 추론 강화 에이전트·도구 에이전트·멀티에이전트·메모리 에이전트 4개 분류 체계. 벤치마크·프레임워크·협력 프로토콜 종합.

### Meta Chain-of-Thought (2025)
- **Anthropic Research**
- **핵심 기여**: "어떻게 생각할지 생각하는" 메타 추론. System 2 사고 방식 LLM 적용.

---

## 7. 특수 주제

### Scaling Laws for Neural Language Models (2020)
- **저자**: Kaplan et al. (OpenAI)
- **arXiv**: [2001.08361](https://arxiv.org/abs/2001.08361)
- **핵심**: 모델 크기 N, 데이터 D, 컴퓨트 C 간 멱함수 관계. 최적 훈련 공식 도출.

### Chinchilla: Training Compute-Optimal LLMs (2022)
- **저자**: Hoffmann et al. (DeepMind)
- **arXiv**: [2203.15556](https://arxiv.org/abs/2203.15556)
- **핵심**: 파라미터와 훈련 토큰은 1:20이 최적. GPT-3가 과소훈련됐음을 증명.
- **실무 영향**: Llama 시리즈가 Chinchilla 법칙을 따름.

### RAG: Retrieval-Augmented Generation for Knowledge-Intensive NLP (2020)
- **저자**: Lewis et al. (Meta)
- **arXiv**: [2005.11401](https://arxiv.org/abs/2005.11401)
- **핵심**: 생성 전 관련 문서 검색 → 컨텍스트 주입. 지식 환각 감소.
- **실무 영향**: 현재 대부분의 엔터프라이즈 AI 제품의 핵심 구조.

---

## 읽기 순서 추천

**입문 (순서대로)**:
1. Attention Is All You Need
2. GPT-3 (Few-Shot Learners)
3. Chain-of-Thought
4. ReAct

**에이전트 개발자**:
1. ReAct → ToT → Building Effective Agents → DeepSeek-R1

**인프라/효율**:
1. LLaMA → FlashAttention-2 → Chinchilla

## Reuse
- 논문 요약 추가 시: arXiv ID, 저자, 핵심 기여(1~2문장), 실무 영향(1문장) 형식 유지.
- 출처 URL은 반드시 포함.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [arXiv.org](https://arxiv.org/)
- [Papers with Code](https://paperswithcode.com/)
