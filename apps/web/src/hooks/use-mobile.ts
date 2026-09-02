import * as React from "react";

const MOBILE_BREAKPOINT = 768;

function subscribeToMobileViewport(onStoreChange: () => void) {
  const mediaQuery = window.matchMedia(
    `(max-width: ${MOBILE_BREAKPOINT - 1}px)`,
  );
  mediaQuery.addEventListener("change", onStoreChange);
  return () => mediaQuery.removeEventListener("change", onStoreChange);
}

function getMobileViewportSnapshot() {
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`).matches;
}

function getServerMobileViewportSnapshot() {
  return false;
}

export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribeToMobileViewport,
    getMobileViewportSnapshot,
    getServerMobileViewportSnapshot,
  );
}
