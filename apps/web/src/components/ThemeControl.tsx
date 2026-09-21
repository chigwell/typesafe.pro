"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type ThemePreference = "light" | "dark" | "system";

const icons = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

function applyTheme(preference: ThemePreference) {
  const dark =
    preference === "dark" ||
    (preference === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.themePreference = preference;
  document.querySelector<HTMLMetaElement>("#theme-color")?.setAttribute("content", dark ? "#101b27" : "#ebf5ff");
}

export function ThemeControl() {
  const [preference, setPreference] = useState<ThemePreference>("system");
  const Icon = icons[preference];

  useEffect(() => {
    let saved: ThemePreference = "system";
    try {
      const value = localStorage.getItem("typesafe-pro-theme");
      if (value === "light" || value === "dark" || value === "system") {
        saved = value;
      }
    } catch {
      saved = "system";
    }
    setPreference(saved);
    applyTheme(saved);

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (document.documentElement.dataset.themePreference === "system") {
        applyTheme("system");
      }
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const update = (value: ThemePreference) => {
    setPreference(value);
    applyTheme(value);
    try {
      localStorage.setItem("typesafe-pro-theme", value);
    } catch {
      // Storage is optional.
    }
  };

  return (
    <details className="theme-control">
      <summary aria-label={`Theme: ${preference}. Change colour theme`} title={`Theme: ${preference}`}>
        <Icon aria-hidden="true" />
      </summary>
      <div className="theme-menu" role="radiogroup" aria-label="Colour theme">
        {(["light", "dark", "system"] as const).map((value) => {
          const OptionIcon = icons[value];
          return (
            <button
              key={value}
              className="theme-option"
              type="button"
              role="radio"
              aria-checked={preference === value}
              onClick={() => update(value)}
            >
              <OptionIcon aria-hidden="true" />
              {value[0].toUpperCase() + value.slice(1)}
            </button>
          );
        })}
      </div>
    </details>
  );
}

