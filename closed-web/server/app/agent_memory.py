"""
agent_memory.py

사관(sagwan) / 부사관(busagwan) 공용 에이전트 메모리 서비스.

설계 (MemGPT, Generative Agents, Reflexion, AriGraph 등 참고):
4계층으로 분리한다.

  1. Persona      — 프로파일 + 정책 파일. 사람이 관리, 불변.
                    `Librarian Profile.md`, `Librarian Policy.md` 등.
  2. Distilled    — 작업 후 LLM 증류로 뽑아낸 장기 규칙/패턴.
                    `Distilled Memory.md`. 에피소드가 일정 수 쌓이면 자동 갱신.
  3. Episodic     — 최근 N개 작업 기록. `Working Memory.md` 의 tail.
                    단기 회상용. 파일은 상한에 도달하면 oldest 섹션 자동 trim.
  4. Related      — 현재 태스크 query 로 검색된 관련 노트 발췌.
                    semantic/lexical hybrid 검색.

공통 워크플로:
    ctx = before_task_context(actor, query)   # 시작 전: 4계층 조합
    ... 실제 작업 ...
    remember(actor, subject, outcome, kind)   # 끝난 후: episodic append
    after_task(actor, llm_invoke=...)         # 끝난 후: distill 임계치 체크 → 장기 정제

actor ∈ {"sagwan", "busagwan"} 만 지원. 그 외엔 ValueError.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.site import get_closed_note, search_closed_notes
from app.vault import append_section, ensure_folder, load_document, write_document

Actor = Literal["sagwan", "busagwan"]

# _ensure_activity_note 중복 생성 방지 캐시 (프로세스 수명 동안 유효)
_activity_notes_seen: set[str] = set()

SAGWAN_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Working Memory.md"
BUSAGWAN_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Subordinate Working Memory.md"
SAGWAN_DISTILLED_PATH = "personal_vault/projects/ops/librarian/memory/Sagwan Distilled Memory.md"
BUSAGWAN_DISTILLED_PATH = "personal_vault/projects/ops/librarian/memory/Busagwan Distilled Memory.md"
SAGWAN_PROFILE_PATH = "personal_vault/projects/ops/librarian/profile/Librarian Profile.md"
SAGWAN_POLICY_PATH = "personal_vault/projects/ops/librarian/policy/Librarian Policy.md"
BUSAGWAN_PROFILE_PATH = "personal_vault/projects/ops/librarian/profile/Subordinate Profile.md"
BUSAGWAN_PLAYBOOK_PATH = "personal_vault/projects/ops/librarian/playbooks/Subordinate Task Playbook.md"

_ACTIVITY_ROOT = "personal_vault/projects/ops/librarian/activity"

# 증류 파라미터
_DISTILL_EPISODE_WINDOW = 40      # 최근 N 에피소드를 보고 증류
_DISTILL_MIN_NEW_EPISODES = 10    # 이만큼 새 에피소드가 쌓여야 distill 실행
_DISTILLED_MAX_CHARS = 8000       # distilled 파일 상한 (넘치면 가장 오래된 섹션부터 잘림)
_WORKING_MEMORY_MAX_CHARS = 60000 # Working Memory 파일 상한 (약 60KB). 넘치면 oldest 섹션 trim.


def _memory_path(actor: Actor) -> str:
    if actor == "sagwan":
        return SAGWAN_MEMORY_PATH
    if actor == "busagwan":
        return BUSAGWAN_MEMORY_PATH
    raise ValueError(f"unknown actor: {actor}")


def _distilled_path(actor: Actor) -> str:
    if actor == "sagwan":
        return SAGWAN_DISTILLED_PATH
    if actor == "busagwan":
        return BUSAGWAN_DISTILLED_PATH
    raise ValueError(f"unknown actor: {actor}")


def _persona_paths(actor: Actor) -> list[str]:
    """계층 1 — 페르소나: 프로파일 + 정책 파일 목록 (불변, 검색 없음)."""
    if actor == "sagwan":
        return [SAGWAN_PROFILE_PATH, SAGWAN_POLICY_PATH]
    return [BUSAGWAN_PROFILE_PATH, BUSAGWAN_PLAYBOOK_PATH]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def remember(
    actor: Actor,
    *,
    subject: str,
    outcome: str,
    kind: str,
) -> None:
    """actor 의 Working Memory 에 append + 일자별 activity 로그에도 함께 append.
    Working Memory 가 _WORKING_MEMORY_MAX_CHARS 를 초과하면 oldest 섹션을 자동 trim."""
    ts = _now_iso()
    mem_path = _memory_path(actor)
    append_section(
        mem_path,
        f"{ts} {kind}",
        "\n".join([
            f"- actor: `{actor}`",
            f"- subject: {subject[:300]}",
            f"- outcome: {outcome[:900]}",
        ]),
    )
    # Working Memory 크기 상한 유지
    try:
        doc = load_document(mem_path)
        body = doc.body or ""
        if len(body) > _WORKING_MEMORY_MAX_CHARS:
            trimmed = _trim_oldest_sections(body, target=_WORKING_MEMORY_MAX_CHARS)
            write_document(path=mem_path, body=trimmed, metadata=doc.frontmatter, allow_owner_change=True)
    except Exception:
        pass
    # 일자별 activity 에도 흔적 (librarian_chat 이 쓰던 위치와 동일)
    daily = f"{_ACTIVITY_ROOT}/{ts[:10]}.md"
    _ensure_activity_note(daily, ts[:10])
    append_section(
        daily,
        f"{ts} {actor}:{kind}",
        "\n".join([
            f"- subject: {subject[:240]}",
            f"- outcome: {outcome[:700]}",
        ]),
    )


def _ensure_activity_note(path: str, date_str: str) -> None:
    if path in _activity_notes_seen:
        return
    try:
        load_document(path)
        _activity_notes_seen.add(path)
        return
    except Exception:
        pass
    ensure_folder(_ACTIVITY_ROOT)
    try:
        write_document(
            path=path,
            title=f"Agent Activity {date_str}",
            kind="reference",
            project="ops/librarian",
            tags=["activity", "agent"],
            body="\n".join([
                "## Summary",
                "사관/부사관의 일일 행동 기록. 반복되는 판단은 Working Memory 나 playbook 으로 승격한다.",
            ]),
            metadata={"visibility": "private", "publication_status": "none"},
            allow_owner_change=True,
        )
    except Exception:
        pass  # activity 로그 실패는 치명적이지 않음
    _activity_notes_seen.add(path)


def gather_persona(actor: Actor) -> list[dict[str, Any]]:
    """계층 1 — 페르소나 메모리: 프로파일 + 정책 파일만. 검색 없음."""
    result: list[dict[str, Any]] = []
    for path in _persona_paths(actor):
        note = get_closed_note(path)
        if note:
            result.append(_note_ctx(note))
    return result


def gather_related(
    query: str,
    *,
    current_note_path: str | None = None,
    search_limit: int = 4,
    exclude_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    """계층 4 — 검색된 관련 메모리: 현재 노트 + semantic/lexical 검색 결과."""
    by_path: dict[str, dict[str, Any]] = {}
    skip = exclude_paths or set()

    if current_note_path and current_note_path not in skip:
        note = get_closed_note(current_note_path)
        if note:
            by_path[current_note_path] = _note_ctx(note, is_current=True)

    if query.strip():
        try:
            results = search_closed_notes(query, limit=search_limit).get("results", [])
        except Exception:
            results = []
        for item in results:
            p = item["path"]
            if p in by_path or p in skip:
                continue
            note = get_closed_note(p)
            if note:
                by_path[p] = _note_ctx(note)

    return list(by_path.values())[:6]


# 하위호환 alias — 기존 호출부가 gather_context 를 직접 쓰는 경우 유지
def gather_context(
    actor: Actor,
    query: str,
    *,
    current_note_path: str | None = None,
    search_limit: int = 4,
) -> list[dict[str, Any]]:
    persona = gather_persona(actor)
    persona_paths = {c["path"] for c in persona}
    related = gather_related(query, current_note_path=current_note_path,
                             search_limit=search_limit, exclude_paths=persona_paths)
    return persona + related


def _note_ctx(note: dict[str, Any], *, is_current: bool = False) -> dict[str, Any]:
    return {
        "path": note["path"],
        "title": note.get("title") or note["path"],
        "summary": note.get("summary") or "",
        "body_excerpt": (note.get("body") or "")[:1800],
        "is_current_note": is_current,
    }


def render_context_snippet(
    ctxs: list[dict[str, Any]],
    *,
    char_budget: int = 2000,
    section_title: str = "참고 메모리",
) -> str:
    """컨텍스트 리스트를 프롬프트에 주입 가능한 짧은 스니펫으로 렌더."""
    if not ctxs:
        return ""
    parts: list[str] = [f"## {section_title}"]
    used = 0
    for ctx in ctxs:
        header = f"### {ctx['title']} ({ctx['path']})"
        body = ctx.get("summary") or ctx.get("body_excerpt") or ""
        block = f"{header}\n{body[:500].strip()}\n"
        if used + len(block) > char_budget:
            block = block[: max(0, char_budget - used)]
            if block:
                parts.append(block)
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts).strip()


def read_distilled(actor: Actor, *, char_budget: int = 2000) -> str:
    """actor 의 증류된 메모리(semantic/procedural) 파일 내용 읽어 반환."""
    try:
        doc = load_document(_distilled_path(actor))
    except Exception:
        return ""
    body = (doc.body or "").strip()
    if not body:
        return ""
    return body[-char_budget:] if len(body) > char_budget else body


def before_task_context(
    actor: Actor,
    query: str,
    *,
    current_note_path: str | None = None,
    total_chars: int = 4000,
) -> dict[str, str]:
    """
    에이전트 작업 시작 전 단일 진입점. 4계층 메모리를 조합한다.

    반환 키:
      persona      — (계층 1) 프로파일 + 정책 (불변) [total_chars 의 15%]
      distilled    — (계층 2) LLM 증류 장기 기억 [35%]
      episodic_tail— (계층 3) 최근 N개 작업 기록 [25%]
      related      — (계층 4) 검색 기반 관련 메모리 [25%]
      combined     — 네 계층 합친 최종 프롬프트 블록
                     (순서: persona → distilled → episodic → related)
    """
    persona_chars   = int(total_chars * 0.15)
    distilled_chars = int(total_chars * 0.35)
    episodic_chars  = int(total_chars * 0.25)
    related_chars   = total_chars - persona_chars - distilled_chars - episodic_chars

    persona_ctxs = gather_persona(actor)
    persona_paths = {c["path"] for c in persona_ctxs}
    persona = render_context_snippet(
        persona_ctxs, char_budget=persona_chars,
        section_title="Persona (에이전트 프로파일 & 정책)",
    )

    distilled = read_distilled(actor, char_budget=distilled_chars)

    tail = recent_memory_tail(actor, max_sections=6, char_budget=episodic_chars)

    related_ctxs = gather_related(
        query,
        current_note_path=current_note_path,
        search_limit=4,
        exclude_paths=persona_paths,
    )
    related = render_context_snippet(
        related_ctxs, char_budget=related_chars,
        section_title="Related Memory (검색된 관련 기억)",
    )

    blocks: list[str] = []
    if persona:
        blocks.append(persona)
    if distilled:
        blocks.append("## Distilled Memory (장기 정제 기억)\n" + distilled)
    if tail:
        blocks.append("## Recent Tasks (최근 작업 기억)\n" + tail)
    if related:
        blocks.append(related)
    combined = "\n\n".join(blocks).strip()

    return {
        "persona": persona,
        "distilled": distilled,
        "episodic_tail": tail,
        "related": related,
        "combined": combined,
    }


def after_task(
    actor: Actor,
    *,
    llm_invoke,  # (prompt: str, *, model: str | None) -> str
    model: str | None = None,
) -> dict[str, Any]:
    """작업 종료 후 호출. 에피소드가 임계치 이상 쌓이면 distill_memory 실행.
    llm_invoke 는 사용 중인 LLM 래퍼를 그대로 전달하면 됨."""
    return distill_memory(actor, llm_invoke=llm_invoke, model=model)


def distill_memory(
    actor: Actor,
    *,
    llm_invoke,  # callable: (prompt: str, *, model: str | None) -> str
    model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    최근 episodic 메모리를 LLM 에게 증류시켜 distilled 파일에 append.
    새 에피소드가 충분히 쌓였을 때만 실행. force=True 면 무조건.

    반환: {"status", "new_episodes", "appended_chars"}
    """
    mem_path = _memory_path(actor)
    distilled_path = _distilled_path(actor)
    try:
        doc = load_document(mem_path)
    except Exception:
        return {"status": "no_memory"}
    body = doc.body or ""
    segments = _split_sections(body)
    if not segments:
        return {"status": "empty"}

    # 마지막 증류 이후 쌓인 에피소드 추정
    last_distilled_at = ""
    try:
        distilled_doc = load_document(distilled_path)
        last_distilled_at = str(distilled_doc.frontmatter.get("last_distilled_at") or "")
    except Exception:
        pass

    new_segments = [
        s for s in segments if _segment_ts(s) > last_distilled_at
    ] if last_distilled_at else segments[-_DISTILL_EPISODE_WINDOW:]

    if not force and len(new_segments) < _DISTILL_MIN_NEW_EPISODES:
        return {"status": "skip", "new_episodes": len(new_segments)}

    window = new_segments[-_DISTILL_EPISODE_WINDOW:]
    episodes_text = "\n\n".join(s[:600] for s in window)[:6000]

    prompt = "\n".join([
        f"너는 OpenAkashic 의 {actor} 의 기억 증류 보조이다.",
        "아래는 최근 에피소드 로그다. 여기서 *재사용 가능한 판단 규칙/패턴* 만 짧게 뽑아라.",
        "원칙:",
        "- 한 줄 규칙 (최대 12개). 중복 제거.",
        "- 반복적으로 관찰된 경우만 규칙화. 일회성 이벤트는 제외.",
        "- approve/defer 의 공통 이유, 자주 터진 실패 유형, 자주 본 태그/프로젝트 등.",
        "- 한국어. 각 줄은 '- ' 시작, 50자 이하.",
        "",
        "## 에피소드",
        episodes_text or "(없음)",
        "",
        "출력 형식: bullet list 만. 서두/결론 금지.",
    ])

    raw = llm_invoke(prompt, model=model)
    if not raw or raw.startswith("[CLI 오류"):
        return {"status": "llm_error", "detail": raw[:200]}

    # bullet 만 추출
    bullets = [ln.rstrip() for ln in raw.splitlines() if ln.strip().startswith("- ")]
    if not bullets:
        return {"status": "no_bullets"}

    ts = _now_iso()
    header_content = "\n".join([f"- distilled_from: {len(window)} episodes", f"- last_distilled_at: `{ts}`", ""]) + "\n".join(bullets)

    # distilled 파일 없으면 생성, 있으면 append + frontmatter 갱신
    _ensure_distilled_note(distilled_path, actor)
    append_section(distilled_path, f"Distillation {ts}", header_content)

    try:
        distilled_doc = load_document(distilled_path)
        fm = dict(distilled_doc.frontmatter)
        fm["last_distilled_at"] = ts
        # 이전 버전 호환: sagwan_distill_count / busagwan_distill_count 도 읽어 합산
        prev = int(fm.pop("sagwan_distill_count", 0) or 0) + int(fm.pop("busagwan_distill_count", 0) or 0)
        fm["distill_count"] = int(fm.get("distill_count") or 0) + prev + 1
        # 파일이 너무 커지면 앞 섹션부터 잘라낸다
        new_body = distilled_doc.body or ""
        if len(new_body) > _DISTILLED_MAX_CHARS:
            trimmed = _trim_oldest_sections(new_body, target=_DISTILLED_MAX_CHARS)
            write_document(path=distilled_path, body=trimmed, metadata=fm, allow_owner_change=True)
        else:
            write_document(path=distilled_path, body=new_body, metadata=fm, allow_owner_change=True)
    except Exception:
        pass

    return {"status": "ok", "new_episodes": len(window), "bullets": len(bullets)}


def _ensure_distilled_note(path: str, actor: Actor) -> None:
    try:
        load_document(path)
        return
    except Exception:
        pass
    from pathlib import Path
    ensure_folder(str(Path(path).parent))
    try:
        write_document(
            path=path,
            title=f"{actor.title()} Distilled Memory",
            kind="reference",
            project="ops/librarian",
            tags=["memory", "distilled", actor],
            body="\n".join([
                "## Summary",
                f"{actor} 의 에피소드 메모리에서 주기적으로 증류된 재사용 규칙/패턴.",
                "자동 생성되며, 사람이 직접 수정해도 좋음.",
            ]),
            metadata={"visibility": "private", "publication_status": "none"},
            allow_owner_change=True,
        )
    except Exception:
        pass


def _split_sections(body: str) -> list[str]:
    segments: list[str] = []
    cur: list[str] = []
    for line in body.splitlines():
        if line.startswith("## ") and cur:
            segments.append("\n".join(cur).strip())
            cur = [line]
        else:
            cur.append(line)
    if cur:
        segments.append("\n".join(cur).strip())
    return [s for s in segments if s]


def _segment_ts(segment: str) -> str:
    """## 2026-04-15T04:10:20Z kind 형식의 첫줄에서 타임스탬프 추출."""
    first = segment.splitlines()[0] if segment else ""
    # '## 2026-04-15T04:10:20Z approval'
    parts = first.replace("## ", "").split()
    return parts[0] if parts else ""


def _trim_oldest_sections(body: str, *, target: int) -> str:
    """body 길이가 target 을 넘으면 가장 오래된 '## ' 섹션부터 제거."""
    segments = _split_sections(body)
    while len("\n\n".join(segments)) > target and len(segments) > 4:
        segments.pop(1)  # index 0 은 preamble(있다면) 또는 첫 섹션, 2번째부터 제거
    return "\n\n".join(segments)


def recent_memory_tail(actor: Actor, *, max_sections: int = 8, char_budget: int = 1400) -> str:
    """actor Working Memory 의 마지막 N 섹션만 잘라낸 스니펫."""
    path = _memory_path(actor)
    try:
        doc = load_document(path)
    except Exception:
        return ""
    segments = _split_sections(doc.body or "")
    tail = segments[-max_sections:] if segments else []
    snippet = "\n\n".join(tail)
    return snippet[-char_budget:] if len(snippet) > char_budget else snippet
