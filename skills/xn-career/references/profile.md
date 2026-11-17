# Candidate profile
1. Get CV text: `document.extract` for PDF/DOCX, or give `profile.ingest` a local .md/.txt `path`.
   For PDF/DOCX extraction, register the exact returned text as evidence with the original local document as `source_ref`; pass its `evidence_id` with `text` to `profile.ingest`. The bridge checks the text digest and workflow ownership.
2. `profile.ingest` returns skills, education, projects and the `unknown` list. Nothing outside the CV is added.
3. Ask the user to confirm unknown facts, then `profile.confirm` with their own words as `quote`: availability, work_authorization, student_status, graduation_year, location, languages, contact.
4. Conflicts (two graduation years, two GPAs) stay open until the user picks one.
Contact details are stored locally and never echoed in outputs.
