import { useEffect, useState } from "react";
import { t } from "../i18n";

type Theme = "auto" | "light" | "dark";

export function applyStoredTheme() {
  const stored = (localStorage.getItem("kp-theme") as Theme | null) ?? "auto";
  if (stored === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", stored);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("kp-theme") as Theme | null) ?? "auto");
  useEffect(() => {
    localStorage.setItem("kp-theme", theme);
    applyStoredTheme();
  }, [theme]);
  return (
    <label className="row small" style={{ gap: 6 }}>
      <span className="muted">{t("common.theme")}</span>
      <select className="input" style={{ width: "auto", padding: "4px 8px" }} value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
        <option value="auto">{t("common.theme_auto")}</option>
        <option value="light">{t("common.theme_light")}</option>
        <option value="dark">{t("common.theme_dark")}</option>
      </select>
    </label>
  );
}
