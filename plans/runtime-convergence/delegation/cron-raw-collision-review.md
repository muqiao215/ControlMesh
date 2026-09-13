# Pending primary review: user keys colliding with internal metadata

Observed 2026-09-13 while AGY review 4 is still running. This is evidence against the
current working candidate, not a claim about its eventual final result. Do not launch
a duplicate worker. Recheck when the existing attempt returns; if still present, send
this defect to the same native conversation with the other final review findings.

Independent Bun reproduction used a fresh in-memory RuntimeDatabase and called
importCronRegistry(db, { jobs: [input] }, { replace: true }), then exportCronRegistry(db).
Input contained valid id/title/schedule/task_folder/agent_instruction and these extra
fields, each set to the literal string `user-field`:

- storage_raw
- storage_version
- storage_spec_digest
- storage_archived
- raw_metadata

All five extra keys disappeared from the exported job. The six ordinary input fields
were preserved. Source inspection identifies putJob's userCleanInput deletions. Renaming
reserved metadata keys merely moves this collision; it does not establish lossless import.

Required acceptance: retain arbitrary JSON keys in the raw payload independently of
storage metadata and normalized columns. No raw key may establish internal authority.
Status updates must not recursively serialize hydrated metadata. Test both first import
and exact replacement, repeated status updates, and export; preserve existing null/BigInt
coverage. Review whether computeJobSpecDigest also excludes arbitrary user fields solely
because they have an internal-looking name, allowing a definition change to escape revision.

No source modifications, real registry access, provider execution or production mutation
were used in this reproduction.
