import { KeyRound, Moon, Sun, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { currentTheme, toggleTheme } from "@/lib/theme";
import { getToken, setToken } from "@/lib/token";

export function SettingsView() {
  const [theme, setTheme] = useState(currentTheme);
  const token = getToken();

  const handleForgetToken = () => {
    setToken(null);
    window.location.reload();
  };

  const handleToggleTheme = () => {
    const next = toggleTheme();
    setTheme(next);
  };

  return (
    <div className="flex-1 overflow-auto p-8 max-w-2xl">
      <h1 className="text-xl font-bold text-fg mb-6">Settings</h1>

      <div className="space-y-6">
        {/* Appearance */}
        <section className="rounded-xl border border-line bg-surface p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-[14px] font-semibold text-fg">Appearance</h2>
              <p className="text-[12.5px] text-muted">
                Switch between dark and light theme
              </p>
            </div>
            <Button
              variant="default"
              size="sm"
              onClick={handleToggleTheme}
              className="gap-2"
            >
              {theme === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />}
              <span className="capitalize">{theme} mode</span>
            </Button>
          </div>
        </section>

        {/* Authentication */}
        <section className="rounded-xl border border-line bg-surface p-5 space-y-4">
          <div>
            <h2 className="text-[14px] font-semibold text-fg flex items-center gap-2">
              <KeyRound className="size-4 text-primary" />
              API Authentication
            </h2>
            <p className="text-[12.5px] text-muted mt-0.5">
              Bearer token used for requests to the local NotebookLM server
            </p>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-line">
            <div className="text-[12.5px] font-mono text-muted">
              {token ? `Bearer ${token.slice(0, 6)}••••••••` : "No token configured"}
            </div>
            <Button
              variant="default"
              size="sm"
              onClick={handleForgetToken}
              className="text-danger hover:text-danger hover:bg-danger/10 border-danger/30 gap-1.5"
            >
              <Trash2 className="size-3.5" />
              Forget token
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}
