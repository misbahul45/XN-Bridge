# Opportunity verification
Prefer structured sources: `opportunities.fetch_ats` for Greenhouse, Lever or Ashby boards of a VERIFIED company. The bridge fetches and stores the raw response; you receive counts.
For other pages, read them with `browser.inspect` or `web.fetch`, register the evidence, then `opportunities.ingest`.
Statuses: OPEN_VERIFIED, LISTED_UNCERTAIN, EXPIRED, INQUIRY_ONLY, UNKNOWN. Never upgrade one yourself. `opportunity.reverify` demotes listings whose evidence went stale.
Posting text with instruction-like patterns is quarantined for human review.

An ATS domain alone does not prove which employer owns its board. Capture a fresh page on the verified employer's domain that links to the exact board, and use it in `company.verify_domain`. Without that link the bridge retains LISTED_UNCERTAIN, including after an otherwise successful ATS fetch. It also checks the final apply destination rather than trusting the display URL.

LinkedIn results (`career.linkedin_jobs`, `career.feed_leads`) are leads. Pass them to `opportunities.ingest` with the LinkedIn read as evidence; they stay LISTED_UNCERTAIN until the verified employer's own domain or ATS board shows the same role. Compare company, title and location before calling two listings the same.
