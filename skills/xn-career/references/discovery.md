# Company discovery
Run the campaign queries with `capability_resolve("web.search")`; if `career.listings` resolves, use it as well.
Pass names and any official-looking URLs to `companies.add`. Duplicates merge by verified domain or exact normalized name; similar names stay separate. LinkedIn, Glints and similar pages never define a company's identity.
Do not claim exhaustive coverage. Report how many sources were searched.

For `career-public`, select explicit public `boards` and use one bounded harvest, then reuse saved evidence. Jobicy automated synchronization must be at least an hour apart; Remotive recommends only a few passes per day. Keep source attribution and original listing links. Tool errors and partial results must be reported. Never call the disabled HN bulk or statistics tools through another path.

Keyword results are candidates, not eligibility judgments: `intern` may also match unrelated words. Apply the campaign's opportunity-category filter and hard requirements locally. Public-board listings stay LISTED_UNCERTAIN until fresh official employer/ATS evidence supports OPEN_VERIFIED.
