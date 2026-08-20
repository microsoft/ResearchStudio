(() => {
  "use strict";

  const STORAGE_KEY = "researchstudio:daily-paper-theme";
  const systemThemeQuery = window.matchMedia?.("(prefers-color-scheme: dark)") || null;
  let preference = "light";

  function systemTheme() {
    if (systemThemeQuery) return systemThemeQuery.matches ? "dark" : "light";
    const hour = new Date().getHours();
    return hour >= 7 && hour < 19 ? "light" : "dark";
  }

  function storedPreference(value = null) {
    try {
      const stored = value ?? localStorage.getItem(STORAGE_KEY);
      return ["system", "dark", "light"].includes(stored) ? stored : "light";
    } catch (_error) {
      return "light";
    }
  }

  function syncMenu() {
    document.querySelectorAll("[data-theme-option]").forEach(option => {
      const selected = option.dataset.themeOption === preference;
      option.classList.toggle("is-active", selected);
      option.setAttribute("aria-current", selected ? "true" : "false");
    });
  }

  function setTheme(nextPreference, persist = false) {
    preference = ["dark", "light"].includes(nextPreference) ? nextPreference : "system";
    const theme = preference === "system" ? systemTheme() : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themePreference = preference;
    syncMenu();
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch (_error) {
        // Theme selection still works for this page when storage is unavailable.
      }
    }
    document.dispatchEvent(new CustomEvent("ui-theme-change", {
      detail: {theme, preference}
    }));
  }

  function initializeMenu() {
    const menus = [...document.querySelectorAll("[data-theme-menu]")];
    document.querySelectorAll("[data-theme-option]").forEach(option => {
      option.addEventListener("click", () => {
        setTheme(option.dataset.themeOption, true);
        const menu = option.closest("[data-theme-menu]");
        if (menu) menu.open = false;
      });
    });
    document.addEventListener("click", event => {
      if (event.target.closest("[data-theme-menu]")) return;
      menus.forEach(menu => { menu.open = false; });
    });
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      menus.forEach(menu => { menu.open = false; });
    });
    syncMenu();
  }

  setTheme(storedPreference(), false);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeMenu, {once: true});
  } else {
    initializeMenu();
  }

  const syncSystemTheme = () => {
    if (preference === "system") setTheme("system", false);
  };
  if (systemThemeQuery?.addEventListener) {
    systemThemeQuery.addEventListener("change", syncSystemTheme);
  } else if (systemThemeQuery?.addListener) {
    systemThemeQuery.addListener(syncSystemTheme);
  }
  window.addEventListener("pageshow", syncSystemTheme);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) syncSystemTheme();
  });
  window.addEventListener("storage", event => {
    if (event.key === STORAGE_KEY) setTheme(storedPreference(event.newValue), false);
  });
})();
