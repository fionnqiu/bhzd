/**
 * Maps historical standalone RAG URLs to the consolidated system-management
 * workflow.  Keeping this pure mapping outside the React route module avoids
 * coupling bookmark compatibility tests to a component-only Fast Refresh file.
 */
export function legacyRagAdminTarget(pathname: string): string {
  const suffix = pathname.replace(/^\/rag-admin(?:\/|$)/, "").replace(/\/$/, "");
  if (!suffix) return "/admin/rag";
  if (suffix === "upload") return "/admin/rag/upload";
  if (suffix === "search-test") return "/admin/rag/search-test";
  if (suffix === "eval-cases") return "/admin/rag/search-test";
  if (suffix === "jobs" || suffix === "ledgers" || suffix === "publish") return "/admin/rag";

  const documentMatch = suffix.match(/^documents\/([^/]+)(?:\/chunks)?$/);
  if (documentMatch) return `/admin/rag/documents/${encodeURIComponent(documentMatch[1])}`;
  return "/admin/rag";
}
