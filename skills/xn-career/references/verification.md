# Company verification
Fetch the company's own site (`web.fetch`), register it with `evidence_register(origin=tool_output, verification=VERIFIED, source_ref=<page url>, content=<page text>, ttl_class=company)`.
Then `company.verify_domain(company_id, domain, evidence_id)`. The evidence must come from that domain, be fresh and carry no injection flags.
A domain already verified for another company is reported as a duplicate, not verified twice.
