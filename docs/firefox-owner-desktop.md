# Direct owner window switching

Request ^2379 corrects the owner UX delivered by ^2378. The earlier report and
scroll/read repair remain historical; this document supersedes only the old
owner Unlock/Lock workflow.

## Product contract

Opening the existing browser.eyrie desktop shows a compact native window
selector immediately. Its selected item identifies the viewed window. Choosing
an item switches directly; **Return to owner** provides a persistent return
path. The list refreshes automatically as task windows open or close. Owner-created
native Firefox windows without an agent lease appear as additional owner
windows; native-tree discovery and exact native identity handle their selection
without claiming or registering them. Manually closed native windows disappear
from the owner list without rewriting the agent registry. There
is no owner link, capability entry, Unlock/Lock control, named-agent instruction,
activation banner or additional authentication prompt.

The native GTK theme supplies light/dark appearance. Before the first agent
acquisition, the native UI identifies its initial owner window without creating
an owner lease or viewer capability. `firefox_service_owner_canary.py` exercises
the real packaged launcher, server and automatically spawned UI, including this
fresh-owner entry before any task allocation.

The dock paints the full
width that it reserves, follows framebuffer shrink/grow, and ellipsizes long
labels inside the selector instead of pushing the return button offscreen.
In v3 xmonad owns Firefox geometry and the dock strut; the legacy resize watcher
must not race the window manager by forcing Firefox across that strut.

## Authority and isolation

The existing Kasm desktop access boundary is unchanged, including its existing
LAN/no-password configuration. This is not a claim that a new owner login was
added. Joy explicitly requested direct controls inside that existing desktop.
No window directory has been added to HTTP, the capability viewer, or public
agent commands.

The resident controller starts the native GTK child and passes exactly one
endpoint of a private unnamed Unix socketpair via an inherited file descriptor.
The descriptor number is not a credential and cannot be used to connect from
another process. No viewer/task capability, token file or clipboard value is
used to authenticate the owner UI. Ordinary remote tools and unrelated
same-UID socket clients have no address at which to open this channel. Local
administrator/root process inspection remains within the pre-existing host
administration boundary.

The channel accepts only bounded `list` and exact-epoch `select` messages. It
returns canonical window labels and current native focus, never viewer secrets,
page contents, URLs or credentials. Native-handle observations are cached by
immutable generation/scope/context/window identity. Selection retains the
existing exact binding validation, Firefox process identity check, one local
xmonad focus message and independent focus readback. It does not acquire a
scope, change custody, renew leases or change an agent binding. Agent input
continues to target the bound content context while Joy views another window.
Protected prompts are neither accepted nor dismissed by selection.

The pre-existing private, peer- and exact-owner-capability-authenticated Unix
socket remains a compatibility/administration path. Its checks are unchanged;
the owner desktop no longer connects to it. A task capability still cannot use
that socket to enumerate windows. The browser service token and capability
viewer routes are unchanged.

A closed/stale selection refuses without choosing another window. Observation
refreshes are not input retries. Lost selection acknowledgements are never
replayed. The child exits on controller-channel closure; normal controller
shutdown also closes its child and private channel.

## Engineering qualification

The permanent native journey is `spec/app/hermes/firefox_owner_desktop_checks.py`,
called by `firefox_public_workflow_canary.py` with
`FIREFOX_DISPOSABLE_CANARY=1` and `FIREFOX_OWNER_PANEL_CANARY=1`. Run only in a
network-disabled disposable Firefox image without owner mounts. Set
`FIREFOX_SCROLL_READ_MODE=all` for the containing real scroll/read workflow.
`GTK_THEME=Adwaita:dark` selects the ordinary dark GTK theme for its second
pixel qualification. Do not treat fixture success as installed acceptance.

The original no-link RED reproduced both rejected behavior and geometry:
Unlock/agent-link gate, with a 468-pixel painted dock inside a 1365-pixel
reserved desktop row. The candidate journey checks direct selection among
three simultaneous windows, owner return, background public input/scroll,
new/closed/stale entries, protected prompt preservation, actual selected item,
framebuffer shrink/grow and screenshots. Light and dark captures are inspected
as pixels, not inferred from style settings.

`test_firefox_owner_desktop.py` retains legacy IPC refusals and adds unnamed
channel, no-capability native listing/current focus, exact selection, malformed
message, capability injection, generation, closed-window and no-replay controls.
The containing window fixture selection retains controller refresh packaging,
creation/recovery, binding, cleanup, consumer and no-replay coverage.

## Release boundary

This source preparation is not installed delivery. Required exact-head CI,
managed image qualification/deployment and actual installed browser.eyrie
owner-control/pixel acceptance remain required. Production profile/session
state, generations and journals must be preserved through the managed delivery
path. Do not repeat the earlier mistake of calling a screenshot of a locked
production toolbar usable owner-window-switching acceptance.
