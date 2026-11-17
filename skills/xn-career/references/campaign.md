# Campaign
`campaign.define` turns the request into categories, locations or scope (LOCAL, REGIONAL, NATIONAL, MULTI_COUNTRY, WORLDWIDE, REMOTE_WORLDWIDE) and queries.
Put must-haves in `strict` (they become hard checks later) and wishes in `preferences`.
Contradictions (remote only and on-site, paid and unpaid) are rejected: ask the user which one wins.
