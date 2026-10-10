import { toast } from "sonner";
import { post, postBlob } from "@/lib/api";

export async function downloadExport(ids: string[], format: "markdown" | "json"): Promise<void> {
  const { blob, filename } = await postBlob("/v1/corpus/export", { ids, format });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast.success(`Exported ${ids.length} ${ids.length === 1 ? "chunk" : "chunks"} as ${format === "json" ? "JSON" : "Markdown"}`);
}

export async function pushAsNote(ids: string[]): Promise<void> {
  const out = await post<{ notes: { notebook_id: string; count: number }[] }>("/v1/corpus/export/note", { ids });
  toast.success(`Pushed ${out.notes.length} ${out.notes.length === 1 ? "note" : "notes"} to NotebookLM`);
}
