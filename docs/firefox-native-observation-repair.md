# Firefox native observation repair (historical)

The [original investigation and qualification record](https://gitlab.joyfullee.me/nest/config/-/blob/6eaeac6c2aafcebd879ee92c0adf3d791fd62354/docs/firefox-native-observation-repair.md)
preserves the Canvas2D stall evidence, the late-creation receipt repair and the
original activation boundary. Its candidate pin, pending status and activation
steps do not describe the current serving revision and must not be replayed.

Current managed configuration keeps accelerated Canvas2D disabled to avoid the
observed stall path. That policy does not diagnose every observation failure.
A Ready pod and working HTTPS ingress do not prove an individual browser
context is responsive or that an earlier action completed.

Use the [current lifecycle and recovery guidance](firefox-reusable-browser-lifecycle.md#conventional-lifecycle).
Preserve the sole correlated observer for an unresolved creation. Do not adopt
unmatched contexts, replay uncertain input, discard journals, or reuse the
original approval for a browser restart or generation retirement.
