# Application preparation
`application.prepare` returns a fact pack and truthful draft skeletons; it refuses ineligible, expired, unknown-status or quarantined listings.
Write drafts only from the fact pack. Run `draft.check` on the final text: UNSUPPORTED_NUMBER, SKILL_NOT_ON_CV and UNVERIFIED_ENTITY must be removed or confirmed by the user.
For forms: `browser.inspect` snapshot, `form.parse_snapshot`, `form.plan`. Fill only FILL, DRAFT_TEXT and UPLOAD items. ASK_USER items (legal, consent, identity, salary) are answered by the user. BLOCKED items (login, CAPTCHA, OTP) are done by the user.
