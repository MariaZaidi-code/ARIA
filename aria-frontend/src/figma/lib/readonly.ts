import { createContext, useContext } from "react";

/**
 * Mobile read-only mode.
 *
 * The backend enforces this with core.deps.require_writable (403 on any
 * mutating route for mobile clients). The frontend mirrors the same verdict
 * so write affordances are hidden/disabled up front instead of failing with
 * an error toast after the click:
 *
 *  - /api/session/status returns `read_only` + `client_type` (server truth)
 *  - until that lands we fall back to a UA guess so a phone never briefly
 *    renders active write buttons.
 */
export const ReadOnlyContext = createContext(false);

export const useReadOnly = () => useContext(ReadOnlyContext);

const MOBILE_UA_RE =
  /Mobile|Android|iPhone|iPad|iPod|Windows Phone|BlackBerry|IEMobile|Opera Mini|Silk/i;

/** UA fallback used only until the first /api/session/status response. */
export function looksLikeMobile(): boolean {
  try {
    return MOBILE_UA_RE.test(navigator.userAgent || "");
  } catch {
    return false;
  }
}

export const READ_ONLY_HINT =
  "Read-only on mobile - connect sources and run analyses on desktop. Saved results and history stay available.";
