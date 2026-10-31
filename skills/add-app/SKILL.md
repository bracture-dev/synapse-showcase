---
name: showcase-add-app
description: Review an available app's exact plan, request confirmation, and verify its installation through Showcase's supplied host capabilities.
---

# Add an available app

Read `guide_status` to learn which apps and capabilities the host actually supplies. If app
planning is unavailable, explain how the person can contact their operator; do not invent a
shell command, endpoint or permission.

1. Call `app_plan` for the app the person chose. Describe its mode, source revision, data path,
   prerequisites and effects. A connection-only plan must not become a package installation.
2. Ask the person to choose Review, then Install or Connect, in Showcase. The screen shows its
   own current plan, and only that click calls `app_install`; the agent cannot. A stale or
   rejected plan is reviewed again, never bypassed.
3. The result is a job, not proof of success. Read `app_job_status` while it runs. Let a runtime
   reconnect finish before retrying. Do not submit the same installation repeatedly.
4. Read `app_status` after completion. Report tools and UI as working only when the host's
   current verification establishes that result. An old failed job is history once the
   current app is verified; an old ready job is not proof the connection still works.

Showcase owns its guide and UI. The supplied host owns acquisition, packages, processes,
workspace configuration and rollback. Missing prerequisites and refused package policy are
handled by the operator. Do not change that policy, create credentials or widen access.

Adding an app does not authorize a new external account or data source. Consent for any
external provider uses the installation's supported setup flow.
