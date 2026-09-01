/* The inline script in <head> resolves the starting theme before first paint
   and writes it to data-theme, so the stylesheet only ever needs one dark
   block and nothing flashes the wrong palette on load. */

const KEY = "theme";
const system = matchMedia("(prefers-color-scheme: dark)");

function savedChoice() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;   // private mode
  }
}

const apply = (theme) => { document.documentElement.dataset.theme = theme; };

export function initTheme(button) {
  // with no explicit choice the page keeps following the system
  system.addEventListener("change", (e) => {
    if (!savedChoice()) apply(e.matches ? "dark" : "light");
  });

  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem(KEY, next); } catch { /* private mode */ }
  });

  // colour transitions only after the first paint, so switching does not
  // animate the whole page in from nothing on load
  requestAnimationFrame(() =>
    document.documentElement.classList.add("theme-ready")
  );
}
