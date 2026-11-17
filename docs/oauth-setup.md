# Local Gmail OAuth bootstrap and current blocker

The owner requested running OAuth setup, then explicitly authorized Playwright-assisted setup. That authorization is retained. It is not treated as a completed account login or a server-verifiable approval receipt.

## Running local setup

`scripts/connect_gmail.py` reuses the installed Gmail provider's OAuth implementation, Google client library, PKCE/state store and private token store. It does not implement a second OAuth broker. It requests Gmail readonly plus identity scopes, uses the guarded loopback callback from `gmail_stdio.py`, and verifies one metadata-only Gmail read before recording account health OK. No message bodies are displayed or messages sent. Unexpected upstream errors print only their type, not potentially secret payloads.

```bash
# Readiness only; exit 2 means a real registered client is still required.
.providers/gmail/bin/python scripts/connect_gmail.py --check

# Import an owner-supplied Google Desktop client and start interactive OAuth.
.providers/gmail/bin/python scripts/connect_gmail.py --client /absolute/path/client_secret.json

# Open Google's Console and wait for the owner's new client download.
.providers/gmail/bin/python scripts/connect_gmail.py --open-console --watch-downloads --wait-for-client 900 --timeout 600
```

The third command was launched in a real GNOME terminal titled **XN-Bridge — Sambungkan Gmail**. Launch returned zero, its process was observed running, and `data/private/gmail-connection-status.json` recorded WAITING_CLIENT. There is no OAuth callback listener until a valid client is available. Client waiting is bounded to 900 seconds for this invocation, followed by at most 600 seconds for consent. A timeout requires rerunning the command; this is not a background service.

The optional download watcher accepts only one new `client_secret*.json` file downloaded during that invocation, using the desktop's XDG Downloads directory. Older files, symlinks and ambiguous multiple downloads are ignored. Client JSON is limited to 64 KiB, must contain Google endpoints/client metadata, is imported with mode 0600, and never silently replaces a different existing client. Client IDs are structurally validated; only Google can establish that a real registration is valid. The wizard uses Desktop clients; Web clients require matching registered redirects and are not accepted by this interactive helper.

Google requires an application registration, enabled Gmail API and owner consent. Its [Gmail Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python) documents Desktop client creation. The [native-app OAuth contract](https://developers.google.com/identity/protocols/oauth2/native-app) specifies browser consent, loopback callbacks and PKCE. No universal client credential can be generated locally for arbitrary applications. No Google project, billing setting, client, consent grant or test-user record was created by the agent.

## Requested Playwright path

The installed Xninetzy public capability API reports a local browser backend and Google/GitHub/Kaggle OAuth adapters. This is verified metadata, not proof that client credentials, a session or the current host approval channel work. Existing infrastructure was checked before trying to substitute another broker.

Actual calls under the owner's explicit request:

| Existing public interface | Intended operation | Actual result |
|---|---|---|
| `security_scope` | One-hour scope for console.cloud.google.com and accounts.google.com | POLICY_HELD: approval_channel_unverified |
| `auth_session_create` | Existing Google OAuth provider, readonly Gmail and identity scopes | POLICY_HELD: approval_channel_unverified |
| `hitl_request_approval` | Concrete scope request carrying the owner's authorization quote | POLICY_HELD: approval_channel_unverified |

No agent-side `hitl_approve` was called: its own tool contract states that an agent tool cannot prove owner approval. The public metadata catalog and installed CLI help exposed no verified channel-repair operation. `xninetzy-cli run --approve` consumes an existing approval identifier; it does not create a trusted channel or authorize inventing an identifier.

The loaded [Playwright skill](/home/misbahul45/.codex/skills/playwright/SKILL.md) delegates connected-browser work to [mcp-workflows.md](/home/misbahul45/.codex/skills/playwright/references/mcp-workflows.md), whose explicit rule is: “if scope is denied: stop, route to owner via HITL”. Browser actions against Google were therefore not performed. This is a failed prerequisite in the existing integration, rather than a claim that Playwright itself returned a browser error. No alternate driver, fabricated receipt, modified Xninetzy configuration or relaxed policy was used.

The remaining browser task requires a genuinely verified owner approval channel through a supported host integration. It cannot be solved by asking for the same chat approval again. Until that integration works, the running local wizard can complete only with the owner's Google client download and consent in the normal browser. Both account OAuth and automated Google Console setup remain BLOCKED; the local bootstrap, validation and callback defenses have fixture/runtime tests.

Evidence: `bench-out/oauth-browser-blocker.json`, `bench-out/provider-install-receipt.json`, enabled `tests/integration/test_career_providers.py` and `tests/unit/test_gmail_setup.py`. No tokens, authorization codes or private client JSON are in those reports.
