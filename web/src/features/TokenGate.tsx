import { KeyRound } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { setToken } from "@/lib/token";

/** First-run prompt for the server token (kept in localStorage across reloads). */
export function TokenGate({ onSaved, rejected }: { onSaved: () => void; rejected: boolean }) {
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(rejected ? "That token was rejected." : null);

  const submit = async () => {
    setChecking(true);
    setError(null);
    try {
      const resp = await fetch("/v1/corpus/health", { headers: { Authorization: `Bearer ${value.trim()}` } });
      if (resp.status === 401 || resp.status === 403) {
        setError("The server rejected this token.");
        return;
      }
      setToken(value.trim());
      onSaved();
    } catch {
      setError("Could not reach notebooklm-server.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="grid h-full place-items-center bg-bg p-6">
      <form
        className="grid w-full max-w-sm gap-3 rounded-xl bg-surface p-5 shadow-pop ring-1 ring-line"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) void submit();
        }}
      >
        <div className="flex items-center gap-2.5">
          <div className="size-[22px] rounded-md bg-gradient-to-br from-[#a78bfa] to-[#7dd3fc]" />
          <h1 className="text-[15px] font-semibold">Corpus Explorer</h1>
        </div>
        <p className="text-[12.5px] text-muted">
          Paste the server token (<code className="font-mono">NOTEBOOKLM_SERVER_TOKEN</code>). It stays in this browser so you
          only do this once.
        </p>
        <Input
          type="password"
          autoFocus
          aria-label="Server token"
          placeholder="Server token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-[12.5px] text-bad">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="md" disabled={!value.trim() || checking}>
          <KeyRound /> {checking ? "Checking…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
