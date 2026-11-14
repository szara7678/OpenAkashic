# Session method read cache

`api/scripts/method_agent.py --read-cache DIRECTORY` enables local presentation
deduplication. Create a unique external directory for every conversation. Do not
reuse a previous session's read state for a new model context: delivery in one
session does not establish reading or attention in another.

Use the actual task's situation, product when known, and desired outcome. Read
the source task before querying; generic wrapper instructions or filenames are
not a meaningful retrieval query. The archive cannot infer the contents of a
local file it was never given.

The client always obtains a fresh server response. It extracts the stored method
core by excluding `outcomes`, `opinions`, and `feedback_counts` from a detail GET,
then fingerprints canonical UTF-8 JSON (sorted keys, compact separators,
ensure_ascii=False). Unknown extra fields affect this fingerprint. Endpoint,
method ID, exact version and core fingerprint isolate artifacts. A full bundle
counts as a delivery only when the complete flag, identity and advertised hash
agree. Search/context snippets and fetch-only references do not count.

The first body remains in the response and a local artifact. On an identical
later read the response contains `method-read-receipt-v1`, the exact identity,
fingerprint and artifact path. Fresh feedback is returned separately as
`fresh_feedback`. Changed feedback is not hidden behind the method-core cache.
Repeated bundle items retain their current feedback and point to the artifact.
The upstream token counter is labeled `server_response_tokens` after client
transformation; it does not claim to count the transformed response or billing.

`--refetch` bypasses suppression. Changed content or versions also return full
text. Corrupt or symlink artifacts fail open to full text and are not overwritten.
The cache never treats an instruction, source URL, report or hash as proof that
a procedure works. `already_read` means delivered by this client, not proof of
model attention, application or successful execution.

This option saves repeated model-context bodies. It does not remove the fresh
network GET, change server method versions, modify public records, require a
reader account, or grant write access. Plain HTTP clients retain their original
response shape and must implement their own session cache if desired. The
optional cache is separate from any claim about real task quality, time or total
provider-token savings; those require the paired execution results.
