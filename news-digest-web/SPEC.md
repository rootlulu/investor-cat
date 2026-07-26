# Frontend redesign

## §G

G1: Turn `news-digest-web` into clear, professional intelligence dashboard; preserve data behavior.

## §C

C1: Work only in `/home/rootlulu/worktrees/news-digest-frontend-redesign` on `codex/frontend-redesign`.
C2: Original dirty checkout `/home/rootlulu/projects` untouched.
C3: Preserve routes, API requests, response shapes, refresh behavior, links, and stored data.
C4: Preserve bounded seven-day/latest-snapshot feeds; presentation-only progressive disclosure.
C5: No new runtime dependency.
C6: Support 1440px desktop and 390px mobile.
C7: Chinese user-facing copy; semantic HTML and keyboard-visible focus.

## §I

routes: `/news`, `/ai`, `/stocks`, `/commodities`, `/energy`, `/consumption`, `/macro`, `/games`, `/xueqiu`
api: existing `/api/*` calls -> unchanged request and response shapes
entry: `frontend/src/App.jsx`
styles: `frontend/src/styles.css`
build: `npm run build`
tests: `python3 -m unittest discover -s tests -v`

## §V

V1: original checkout HEAD/status before vs after -> identical.
V2: 390px shell -> non-sticky tall header, single-line horizontal page nav, no document horizontal overflow.
V3: mobile `.page-nav a`, primary/secondary/load-more actions, page tabs, section jump links -> min 44px target; visible `:focus-visible`; reduced-motion honored.
V4: status -> compact summary by default; failure/partial anomaly visible without expansion; full source/error detail remains accessible.
V5: news -> <=12 initial cards/column; first item emphasized; remaining cards compact; load-more preserves full snapshot.
V6: AI news -> <=24 initial cards/tab; explicit load-more preserves full snapshot.
V7: stocks -> market overview then watchlist then industry financing; section jump nav exposes hierarchy.
V8: macro @390px -> card rows, no table horizontal scroll; all 7 fields retained.
V9: surfaces/colors -> one accent/page; red/green semantic only; no position-based section color rotation.
V10: all routes @1440px and representative routes @390px -> render, zero console errors, no document horizontal overflow.
V11: `npm run build` and Python unittest suite -> exit 0.
V12: route hrefs, active-page state, external links, tabs, refresh actions -> existing behavior preserved.

## §T

id|status|task|cites
T1|x|redesign shell, nav, status, tokens, focus|V2,V3,V4,V9,V12
T2|x|add progressive disclosure and feed hierarchy|V5,V6
T3|x|reorder stocks and make macro mobile-native|V7,V8
T4|x|build, tests, desktop/mobile browser QA|V1,V10,V11

## §B

id|date|cause|fix
