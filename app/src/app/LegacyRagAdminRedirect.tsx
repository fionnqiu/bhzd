import { Navigate, useLocation, useParams } from "react-router-dom";
import { legacyRagAdminTarget } from "./legacyRagRoutes";

/**
 * Redirects old RAG-portal bookmarks without mounting the deleted portal shell.
 * The parent route owns the system-admin guard; this component only preserves
 * the legacy suffix and query string while selecting the current destination.
 */
export default function LegacyRagAdminRedirect() {
  const params = useParams();
  const location = useLocation();
  const wildcard = params["*"] ?? "";
  const target = legacyRagAdminTarget(`/rag-admin/${wildcard}`);
  return <Navigate to={`${target}${location.search}`} replace />;
}
