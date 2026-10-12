/** Opens Neo4j Browser with the query pre-filled in its editor (press Run, or Ctrl/Cmd+Enter). */
export function browserLink(browserUrl: string, cypher: string): string {
  const base = browserUrl.endsWith("/") ? browserUrl : `${browserUrl}/`;
  return `${base}?cmd=edit&arg=${encodeURIComponent(cypher)}`;
}
