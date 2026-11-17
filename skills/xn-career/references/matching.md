# Matching
`match.run` evaluates hard checks first (work authorization, location, student status, graduation year, duration, mandatory skills, language, campaign must-haves). Each is PASS, FAIL or UNKNOWN.
Order: ELIGIBLE, then UNKNOWN_ELIGIBILITY, never INELIGIBLE. The soft score (skills, projects, experience, role, arrangement, learning) is shown with its weights and coverage.
Ask the user to settle UNKNOWN checks with `profile.confirm` before preparing an application.
