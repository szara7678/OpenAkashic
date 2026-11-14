"""Classification uses declared tags, consistently across public read views."""
import pytest

from app.research_method_graph import catalog, domain_for, network_graph
from app.research_method_store import MethodStore
from app.research_store import ResearchStore


@pytest.mark.parametrize("tags,expected", [
    (["documented-exception", "version-scoped", "duckdb"], "개발·운영"),
    (["documented-exception", "version-scoped", "tanstack"], "개발·운영"),
    (["documented-exception", "version-scoped", "streamlit"], "개발·운영"),
    (["SQLite", "백업", "복원검증", "Python", "데이터무결성"], "개발·운영"),
    (["장애대응", "서비스운영", "플레이북"], "개발·운영"),
    (["Kubernetes", "서비스운영", "가용성"], "개발·운영"),
    (["CI", "산출물", "빌드"], "개발·운영"),
    (["보안", "CI", "자격정보"], "개발·운영"),
    (["배포", "승인", "CI"], "개발·운영"),
    (["코드리뷰", "피드백", "추적"], "개발·운영"),
    (["문서검토", "변경기록", "보고"], "글쓰기·전달"),
    (["문서검토", "댓글", "액션아이템"], "글쓰기·전달"),
    (["문서검토", "제안편집", "승인"], "글쓰기·전달"),
    (["코드리뷰", "협업", "변경관리"], "팀 의사결정"),
    (["문서검토", "버전비교", "협업"], "팀 의사결정"),
    (["mvp-e2e-demo"], "기타"),
    (["documented-exception", "version-scoped", "unknown-product"], "기타"),
    (["조사·분석", "CI"], "조사·분석"),
    (["디자인"], "디자인"),
    (["개발·운영"], "개발·운영"),
])
def test_declared_domains_and_legacy_precedence(tags, expected):
    # An attractive title is insufficient evidence for a domain assignment.
    assert domain_for({"tags": tags, "title": "SQLite research design"}) == expected


def test_catalog_network_and_scope_share_classification_without_writing(tmp_path):
    from app.research_method_search import scope_match

    store = MethodStore(ResearchStore(tmp_path / "public.sqlite3"))
    payload = dict(title="Review changes", situation="A review has multiple requests",
                   goal="Track each response", constraints=[], steps=["Link the response"],
                   success_criteria=["Each request has a response"], limitations=["Public fixture"],
                   tags=["코드리뷰", "피드백", "추적"], public_source_only=True, agent_name="fixture")
    saved = store.create_method(payload, "classification-fixture")
    before = open(store.db_path, "rb").read()

    listing = catalog(store, domain="개발·운영")
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == saved["id"]
    graph = network_graph(store, domain="개발·운영")
    assert graph["scope"]["methods_shown"] == 1
    assert {node["label"] for node in graph["nodes"] if node["kind"] == "category"} == {"개발·운영"}
    assert scope_match(saved, domain="개발·운영")
    assert not scope_match(saved, domain="기타")
    assert open(store.db_path, "rb").read() == before
