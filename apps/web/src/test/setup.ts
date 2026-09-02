import "@testing-library/jest-dom/vitest";

// JSDOM does not currently expose PointerEvent, while Base UI uses it when a
// checkbox forwards a click with keyboard/pointer modifiers. MouseEvent
// provides the event fields exercised by our component tests.
if (typeof window !== "undefined" && !window.PointerEvent) {
  window.PointerEvent = MouseEvent as typeof PointerEvent;
}
