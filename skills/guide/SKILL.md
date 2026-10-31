---
name: showcase-guide
description: Help a person learn an MCP app through Showcase's shared guide and practice board.
---

# Guide someone through Showcase

Read `guide_status` first and continue from the person's chosen chapter. Offer one useful
action, let them try it, then explain the observed result. Questions do not require changing
the screen or saved state.

`guide_step` selects a chapter and can record completion or a skip. A skipped step does not
count as completed. `guide_preferences` saves pace and the guide's own appearance. Use
`guide_view` to focus or pause the illustration; change zoom only when asked.

The person may click while you work. Read current state before using a card ID or assuming a
chapter is still selected. `board_add` and `board_move` affect only the practice board. They
do not create real tasks in another app. Read back the changed card before describing success.

The screen and an agent use the same tools and saved state, except that only the screen
installs an app. All arrows and animations remain
inside Showcase. No guide tool controls the host's DOM, acquires a model key or signs in to an
external provider. Keep keys out of messages and tool arguments.

External data services are configured through the installation's supported admin setup.
`catalog_list` describes available choices; it does not prove installation or authorization.

An external coding agent can call `guide_connection_check` when asked. The resulting timestamp
proves a tool call reached this guide. It does not prove a model-provider reply or grant tools
from other connected apps. Provider setup and connection consent remain with their owner.

For the full tool list, read [the README](../../README.md) from a checkout. Through MCP alone,
use the available guide tools rather than assuming local-file access.
