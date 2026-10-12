// Same palette as kgdemo/viz.py and neo4j/browser_style.grass, so the app and Neo4j Browser look alike.
const LABEL_COLORS: Record<string, string> = {
  Client: "#E8A33D",
  Account: "#F2C879",
  Fund: "#4C8BF5",
  Company: "#7B61FF",
  Theme: "#E5484D",
  Concept: "#F28B82",
  Person: "#2BB673",
  Advisor: "#1E8E5A",
  Document: "#8D99AE",
  Meeting: "#00A3BF",
  Committee: "#0B6E7F",
  Decision: "#D6336C",
  Transaction: "#B0B7C3",
  Chunk: "#DADDE2",
};

export const LABEL_SIZES: Record<string, number> = {
  Client: 34, Theme: 34, Committee: 30, Fund: 28, Decision: 26, Meeting: 26, Company: 24, Person: 22,
  Advisor: 24, Document: 20, Concept: 20, Account: 20, Transaction: 14, Chunk: 12,
};

export const LABEL_ORDER = [
  "Client", "Advisor", "Account", "Fund", "Company", "Theme", "Concept", "Person", "Document", "Meeting",
  "Committee", "Decision", "Transaction", "Chunk",
];

export function colorFor(label: string): string {
  return LABEL_COLORS[label] ?? "#A5ABB6";
}

export const DOC_TYPE_COLORS: Record<string, string> = {
  "Meeting Notes": "#00A3BF",
  "CRM Note": "#E8A33D",
  "Research Report": "#4C8BF5",
  Email: "#7B61FF",
  "IC Memo": "#D6336C",
  "Due Diligence": "#2BB673",
};
