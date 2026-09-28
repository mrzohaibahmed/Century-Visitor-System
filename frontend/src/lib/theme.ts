/**
 * Light/dark theme. The choice lives in a cookie so the server renders the right theme in the
 * first HTML (no flash, works without JavaScript, no inline script to allow under a CSP).
 * Dark is the default.
 */
export type Theme = "dark" | "light";

export const THEME_COOKIE = "cg_theme";
export const SIDEBAR_COOKIE = "cg_sidebar";

const ONE_YEAR = 60 * 60 * 24 * 365;

export function themeFrom(value: string | undefined): Theme {
  return value === "light" ? "light" : "dark";
}

/** Applies a theme now and remembers it for the next page load. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.cookie = `${THEME_COOKIE}=${theme}; Path=/; Max-Age=${ONE_YEAR}; SameSite=Lax`;
}

export function rememberSidebar(collapsed: boolean): void {
  document.cookie = `${SIDEBAR_COOKIE}=${collapsed ? "collapsed" : "expanded"}; Path=/; Max-Age=${ONE_YEAR}; SameSite=Lax`;
}
