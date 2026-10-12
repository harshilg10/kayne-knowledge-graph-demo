// Payloads returned by the Python API (kgdemo/server.py).

export interface GraphNode {
  id: string;
  label: string;
  labels: string[];
  caption: string;
  properties: Record<string, unknown>;
  position?: { x: number; y: number };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
  inferred: boolean;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  browser_cypher?: string;
}

export interface Status {
  neo4j: { ok: boolean; version?: string; edition?: string; nodes?: number; rels?: number; error?: string };
  llm: { available: boolean; model: string };
  as_of: string;
  firm: string;
  hero: { client_id: string; client_name: string; doc_id: string; theme: string };
  browser_url: string;
  neo4j_user: string;
}

export interface Overview {
  book: { clients: number; accounts: number; transactions: number; aum_usd: number; documents: number };
  graph: { ok: boolean; labels?: Record<string, number>; nodes?: number; rels?: number };
}

export interface TableInfo {
  name: string;
  rows: number;
  columns: string[];
  description: string;
}

export interface StructuredIndex {
  systems: { system: string; tables: TableInfo[]; rows: number }[];
  hero_client: string;
}

export type Row = Record<string, unknown>;

export interface StructuredTable {
  name: string;
  columns: string[];
  rows: Row[];
  total: number;
  filtered: boolean;
}

export interface DocSummary {
  doc_id: string;
  doc_type: string;
  title: string;
  date: string;
  source_system: string;
  source_path: string;
  file_name: string;
  file_ext: string;
}

export interface DocDetail extends DocSummary {
  text: string;
  body_offset: number;
  metadata: Record<string, unknown>;
}

export interface DocIndex {
  types: string[];
  counts: Record<string, number>;
  documents: DocSummary[];
  hero_doc_id: string;
}

export interface ModelPayload {
  schema: Graph;
  themes: { id: string; name: string; definition: string; synonyms: string[]; concepts: { name: string; synonyms: string[] }[] }[];
}

export interface KeywordVsSemantic {
  phrase: string;
  keyword_total: number;
  semantic_total: number;
  missed_total: number;
  missed: { doc_id: string; date: string; title: string; type: string; via: string[] }[];
  cypher: string;
}

export interface ExtractSources {
  documents: DocSummary[];
  default_doc_id: string;
  paste_sample: string;
  engines: string[];
  llm_model: string;
}

export interface ExtractEntity {
  key: string;
  label: string;
  id: string;
  name: string;
  identified_by: string;
  mentions: string[];
  spans: [number, number][];
}

export interface ExtractResult {
  doc_id: string;
  engine: string;
  warnings: string[];
  record: { doc_id: string; title: string; doc_type: string; date: string; text: string; body_offset: number };
  entities: ExtractEntity[];
  relationships: { source: string; type: string; target: string; evidence: string; inferred: boolean; via?: string | null }[];
  graph: Graph;
  in_graph: boolean;
}

export interface QueryDef {
  id: string;
  title: string;
  question: string;
  cypher: string;
  params: Record<string, string>;
  shows: "table" | "graph" | "both";
  group: string;
  browser_cypher: string;
}

export interface QueryResult {
  id: string;
  params: Record<string, string>;
  columns?: string[];
  rows?: Row[];
  graph?: Graph;
  ms: number;
}

export interface Fact {
  kind: string;
  text: string;
  sources: string[];
  data: Record<string, unknown>;
}

export interface Chunk {
  chunk_id: string;
  text: string;
  score: number;
  doc_id: string;
  title: string;
  doc_type: string;
  date: string;
  source_system: string;
}

export interface RagSide {
  mode: string;
  question: string;
  strategy: string;
  linked: { mentions?: { label: string; name: string; id?: string }[]; since?: string | null; as_of?: string } & Record<string, unknown>;
  chunks: Chunk[];
  facts: Fact[];
  cypher: string[];
  context: string;
  answer: string;
  answer_engine: string;
  sources: { id: string; title: string; type: string; date: string; system: string }[];
  timings_ms: Record<string, number>;
  warnings: string[];
  graph: Graph;
}

export interface RagCompare {
  standard: RagSide;
  graph: RagSide;
  strategy_label: string;
  coverage: { items: { label: string; standard: boolean; graph: boolean }[]; standard: number; graph: number; total: number };
}

export interface ValueCard {
  title: string;
  claim: string;
  proof: string;
}
