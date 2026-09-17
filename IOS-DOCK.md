# Mobile Safari dock compatibility

STATUS: The user confirmed production working BEFORE this experiment shipped.
The experimental VisualViewport controller is not imported and its CSS was
removed before the operations release. Production retains the simple body portal.
The notes below describe the unshipped experiment, not live behavior.

The body portal alone did not resolve the user's Safari scroll report.
The exact iOS version and whether the gesture involves root-edge bounce are
not yet known; this change is a compatibility mitigation, not a confirmed
device-level root-cause diagnosis.

- Desktop retains the existing bottom-fixed positioning.
- Touch layouts anchor from the top and use VisualViewport height/offset,
  avoiding reliance on Safari's bottom-fixed toolbar adjustment.
- Resize, scroll, orientation and page restoration events are coalesced into
  one animation frame. No touch event is cancelled. Listeners are removed
  when the dock unmounts.
- Pinch zoom keeps native behavior. Missing VisualViewport uses CSS height
  fallbacks. Existing login/admin visibility rules remain unchanged.
- Safari touch pages with a dock suppress root overscroll. This intentionally
  also disables the browser's pull-to-refresh gesture on those pages; the
  browser reload control still works. Authentication/admin pages are unaffected.

Tests: `node --test portal/dock.test.mjs` covers simulated viewport transitions,
event coalescing, teardown and CSS contracts. It is not an iPhone/Safari test.
Real-device acceptance still needs normal scroll, top/bottom overscroll,
toolbar expand/collapse, orientation, input keyboard and return from background.

Reference: https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport
