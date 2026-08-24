/**
 * Token storage.
 *
 * The token lives in `localStorage`, which means any script running on this
 * origin can read it. That is a real and deliberate limitation, not an
 * oversight: the backend issues a bearer token rather than setting a cookie,
 * so there is nowhere safer for a static frontend to keep it.
 *
 * The fix is an httpOnly, SameSite cookie set by the backend on login — noted
 * in the README as the first thing to change before this faces the internet.
 */
const TOKEN_KEY = "anime_pipeline_token";

export function saveToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Private mode, or storage disabled. The session still works for as long
    // as the tab lives; it just will not survive a reload.
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}
