INSERT INTO claims (id, text, status, confidence, source_weight, claim_role, metadata)
VALUES
    ('00000000-0000-0000-0000-000000000101', 'OpenAkashic v1은 사람 대상 답변기가 아니라 claim/evidence/capsule을 검색해 반환하는 공용 기억 저장소다.', 'accepted', 0.950, 0.900, 'core', '{"tags":["openakashic","definition"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000102', 'OpenAkashic v1의 읽기 경로는 DB 조회, 검색, 랭킹, 결정적 패키징으로 끝나야 하며 매 요청마다 LLM을 호출하지 않는다.', 'accepted', 0.930, 0.900, 'core', '{"tags":["openakashic","read-path"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000103', 'OpenAkashic v1에서 지식의 중심 단위는 entity가 아니라 claim이며, mention은 검색 boost를 위한 보조 구조다.', 'accepted', 0.920, 0.880, 'core', '{"tags":["openakashic","claim-first","mention"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000104', 'Capsule은 예쁜 자연어 답변문이 아니라 관련 claim, 핵심 요점, 주의점, 근거 포인터를 담은 구조화된 기억 패킷이다.', 'accepted', 0.940, 0.900, 'core', '{"tags":["openakashic","capsule"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000105', 'OpenAkashic v1에서 accepted claim은 evidence를 따라갈 수 있어야 한다.', 'accepted', 0.900, 0.850, 'support', '{"tags":["openakashic","evidence"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000106', '쓰기 API를 공개 도메인에 노출할 때 인증 없이 열어두면 임의 claim 주입 위험이 있다.', 'accepted', 0.880, 0.820, 'caution', '{"tags":["warning","api","security"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000107', '〜ちゃう는 〜てしまう의 구어체 축약 표현으로 볼 수 있다.', 'accepted', 0.890, 0.800, 'core', '{"tags":["japanese","grammar"]}'::jsonb),
    ('00000000-0000-0000-0000-000000000108', '격식 있는 문장이나 정중한 문맥에서는 〜ちゃう 사용에 주의해야 한다.', 'accepted', 0.860, 0.780, 'caution', '{"tags":["japanese","grammar","formal","warning"]}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO evidences (id, claim_id, source_type, source_uri, excerpt, note)
VALUES
    ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000101', 'project_note', 'OpenAkashic/plan/v1_qna.md', 'OpenAkashic v1은 claim/evidence를 검색하고 capsule로 패키징하는 공용 기억 저장소로 정의된다.', 'Seeded from local planning notes.'),
    ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000102', 'project_note', 'OpenAkashic/plan/idea1.md', '읽기 경로는 DB 조회, 검색, 랭킹, 사전 계산 또는 결정적 조립으로 끝낸다.', 'Seeded from local planning notes.'),
    ('00000000-0000-0000-0000-000000000203', '00000000-0000-0000-0000-000000000103', 'project_note', 'OpenAkashic/plan/v1_qna.md', 'v1의 필수는 entity가 아니라 mention이며, claim-centric memory store로 간다.', 'Seeded from local planning notes.'),
    ('00000000-0000-0000-0000-000000000204', '00000000-0000-0000-0000-000000000104', 'project_note', 'OpenAkashic/plan/idea1.md', 'capsule은 생성문이 아니라 기억 패킷이다.', 'Seeded from local planning notes.'),
    ('00000000-0000-0000-0000-000000000205', '00000000-0000-0000-0000-000000000105', 'project_note', 'OpenAkashic/plan/v1_qna.md', 'evidence-gated 원칙에 따라 accepted claim은 evidence가 있어야 한다.', 'Seeded from local planning notes.'),
    ('00000000-0000-0000-0000-000000000206', '00000000-0000-0000-0000-000000000106', 'operational_note', 'local://deployment', 'Public mutation endpoints should require a write key.', 'Deployment caution.'),
    ('00000000-0000-0000-0000-000000000207', '00000000-0000-0000-0000-000000000107', 'example_note', 'OpenAkashic/plan/idea1.md', '문서 예시에서 〜ちゃう는 〜てしまう의 구어체 축약으로 다룬다.', 'Seeded example.'),
    ('00000000-0000-0000-0000-000000000208', '00000000-0000-0000-0000-000000000108', 'example_note', 'OpenAkashic/plan/idea1.md', '격식 있는 문장에서는 〜ちゃう 사용 주의.', 'Seeded example.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO claim_mentions (claim_id, mention_text, normalized_mention, role)
VALUES
    ('00000000-0000-0000-0000-000000000101', 'OpenAkashic v1', 'openakashic v1', 'subject'),
    ('00000000-0000-0000-0000-000000000101', 'claim/evidence/capsule', 'claim evidence capsule', 'object'),
    ('00000000-0000-0000-0000-000000000102', 'read path', 'read path', 'subject'),
    ('00000000-0000-0000-0000-000000000102', 'LLM', 'llm', 'object'),
    ('00000000-0000-0000-0000-000000000103', 'claim', 'claim', 'subject'),
    ('00000000-0000-0000-0000-000000000103', 'mention', 'mention', 'object'),
    ('00000000-0000-0000-0000-000000000104', 'capsule', 'capsule', 'subject'),
    ('00000000-0000-0000-0000-000000000106', '쓰기 API', '쓰기 api', 'subject'),
    ('00000000-0000-0000-0000-000000000107', '〜ちゃう', '〜ちゃう', 'subject'),
    ('00000000-0000-0000-0000-000000000107', '〜てしまう', '〜てしまう', 'object'),
    ('00000000-0000-0000-0000-000000000108', '〜ちゃう', '〜ちゃう', 'subject')
ON CONFLICT (claim_id, normalized_mention) DO NOTHING;

INSERT INTO claim_links (from_claim_id, to_claim_id, link_type)
VALUES
    ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102', 'supports'),
    ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000103', 'supports'),
    ('00000000-0000-0000-0000-000000000104', '00000000-0000-0000-0000-000000000101', 'related'),
    ('00000000-0000-0000-0000-000000000108', '00000000-0000-0000-0000-000000000107', 'related')
ON CONFLICT (from_claim_id, to_claim_id, link_type) DO NOTHING;

INSERT INTO capsules (id, title, summary, key_points, cautions, source_claim_ids, confidence, metadata)
VALUES
    (
        '00000000-0000-0000-0000-000000000301',
        'OpenAkashic v1 core',
        '["OpenAkashic v1은 답변기가 아니라 공용 기억 저장소다.", "claim/evidence를 검색하고 capsule로 패키징해 외부 에이전트에 반환한다."]'::jsonb,
        '[{"text":"OpenAkashic v1은 사람 대상 답변기가 아니라 claim/evidence/capsule을 검색해 반환하는 공용 기억 저장소다.","claim_id":"00000000-0000-0000-0000-000000000101"},{"text":"읽기 경로는 DB 조회, 검색, 랭킹, 결정적 패키징으로 끝나야 한다.","claim_id":"00000000-0000-0000-0000-000000000102"},{"text":"v1의 중심 단위는 entity가 아니라 claim이며 mention은 검색 boost 보조 구조다.","claim_id":"00000000-0000-0000-0000-000000000103"}]'::jsonb,
        '[{"text":"쓰기 API를 공개 도메인에 인증 없이 열어두면 임의 claim 주입 위험이 있다.","claim_id":"00000000-0000-0000-0000-000000000106"}]'::jsonb,
        ARRAY['00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000102','00000000-0000-0000-0000-000000000103','00000000-0000-0000-0000-000000000104','00000000-0000-0000-0000-000000000105','00000000-0000-0000-0000-000000000106']::uuid[],
        0.930,
        '{"tags":["openakashic","v1"]}'::jsonb
    ),
    (
        '00000000-0000-0000-0000-000000000302',
        '〜てしまう / 〜ちゃう',
        '["〜ちゃう는 〜てしまう의 구어체 축약 표현으로 볼 수 있다.", "격식 있는 문맥에서는 사용에 주의한다."]'::jsonb,
        '[{"text":"〜ちゃう는 〜てしまう의 구어체 축약 표현으로 볼 수 있다.","claim_id":"00000000-0000-0000-0000-000000000107"}]'::jsonb,
        '[{"text":"격식 있는 문장이나 정중한 문맥에서는 〜ちゃう 사용에 주의해야 한다.","claim_id":"00000000-0000-0000-0000-000000000108"}]'::jsonb,
        ARRAY['00000000-0000-0000-0000-000000000107','00000000-0000-0000-0000-000000000108']::uuid[],
        0.880,
        '{"tags":["japanese","grammar"]}'::jsonb
    )
ON CONFLICT (id) DO NOTHING;
