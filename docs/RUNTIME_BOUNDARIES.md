# LegalAI Runtime Boundaries

## Normal operating path

1. Attorney workspace app
2. Canonical B2 case/draft records
3. Internal draft worker queue
4. GitHub Actions test → deploy → Railway verification → Pushover receipt

The normal path does not require manual Railway SSH, Mission Control copy/paste, or a gateway deployment.

## Gateway role

The gateway is a compatibility and protection boundary only for functions that still require it:

- authenticated request creation and cancellation;
- verified-record delivery/search that has not yet moved to the app's B2 reader;
- legacy case portals.

It is not part of the production release controller and is not the canonical store.

## Data rules

- B2 holds immutable source ZIPs and authoritative request, status, draft, audit, and review records.
- The app reads draft list/status/detail directly from B2 when its configured credentials are available; it falls back to the gateway only for compatibility.
- The worker is the only component that can generate a draft.
- A model call requires a separately approved request; no read-only path can create one.

## Simplification sequence

1. Direct B2 draft reads — complete.
2. Direct B2 review/packet reads — next.
3. Move request creation/cancellation behind the app's authenticated queue boundary.
4. Retire gateway endpoints only after production parity and rollback evidence.

Each step must preserve SHA verification, Basic Auth, four-state execution reporting, and the GitHub Actions release gate.
