The Cedar pilot team wants to know whether assisted handling performed better than standard handling. Analyze /task/input/cases.csv and prepare a concise, readable offline report for an operations lead. This is an observational service log, not a randomized experiment. The log contains one row per case; a blank resolved value means outcome unknown, not failure. East and West had different case mixes, so a pooled comparison alone can mislead.

Write a reproducible /work/analysis.py using only installed dependencies. Produce:
1. summary.csv with exactly six rows: one row for each service×branch pair plus one pooled row per service with branch ALL. Columns, exactly: service,branch,n_total,n_known,n_missing,n_success,success_rate. Services are assisted and standard. Rates use known outcomes as denominator and are numeric proportions.
2. comparison.json with numeric keys pooled_difference_pp and equal_branch_difference_pp (assisted minus standard in percentage points). For equal-branch comparison, weight the East and West known-outcome success rates equally within each service.
3. report.html, a self-contained readable report explaining pooled and equal-branch results, direction changes, missingness, and why this log does not establish causation. Include a practical next step that fits that evidence. Be clear about which denominator each displayed percentage uses. Do not silently impute unknown outcomes.
4. QA.md documenting actual checks and results.

Use no external requests. Run your analysis and relevant verification, inspect the report if tools permit, and return output paths plus material limitations in a normal final response. You may use any useful supplied references; do not assume that file profiling alone answers the comparison question.

Also write /work/README.md with exact commands run, result summary, source skill/version identifiers actually used (or say none), which guidance you applied, and limitations or corrections. Do not claim checks you did not execute.
