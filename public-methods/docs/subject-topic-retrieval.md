# Declared subject/topic retrieval policy v1

The public search API remains anonymous and read-only. This policy adds no
methods, changes no exact versions, and changes neither embedding floors nor
embedding provenance. Contributor method/citation text remains untrusted data.

For semantic and hybrid search, the bounded current public corpus supplies a
subject vocabulary. A Latin alphanumeric editorial tag must occur in written
method identity or constraints to qualify. A source host label must also occur
in written method identity, constraints, source title or stored quote. Common
infrastructure host labels are excluded. URL paths alone do not identify a
subject. This is a disclosed retrieval heuristic, not a verified product
ontology, compatibility claim, or substitute for explicit scope parameters.

When a query names vocabulary subjects, a method must declare all those
subjects and may not name an additional product subject in its title. Missing
labels are unknown and excluded for this retrieval request, not proven
incompatible. Each query axis must also share a non-subject topic term with the
method's title, axes, procedure, citation title or stored quote. Identifiers
retain their original token and camel-case parts; simple plural variants are
included. All subject token variants are removed from topic evidence so a
product name alone cannot rescue an unrelated objective. Queries without
recognized subjects retain the prior semantic paraphrase route. Unknown
products outside this finite vocabulary are not recognized automatically;
explicit product scope still performs its exact editorial-tag filter.

Semantic candidates still require both frozen axis floors. Hybrid additionally
admits separately labeled `declared_subject_topic_lexical` candidates with exact
subject and per-axis topic overlap. Such rows set `semantic_eligible=false`,
retain actual similarities and floors, and have no semantic rank. Independent
lexical and semantic ranks are combined with reciprocal rank fusion. This route
can surface a partial method related to a named product; it does not establish
that it solves the complete query or that its source supports every requested
operation. Full-method and source review remain necessary.

Both routes require current exact-version/full-body/content hashes, matching
pinned index provenance and a successful query embedding request. Missing,
stale or inconsistent entries are excluded; unavailable index/service causes
abstention. Structured constraint conflicts and explicit domain/product scope
still precede ranking. Lexical-only mode retains its existing behavior.

Diagnostics must preserve misses and unrelated candidates. Current development
diagnostics recover English Kubernetes and pandas queries and reject a Python
HTTP request with no matching method. Other related pandas records can rank
above a missing-value policy record, and generic no-product semantic queries
can still have unrelated extra candidates. This is retrieval evidence, not a
held-out task-quality, billed-token, or real-user efficiency result.
