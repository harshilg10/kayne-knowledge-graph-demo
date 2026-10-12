export interface Step {
  path: string;
  number: number | null;
  title: string;
  nav: string;
}

export const STEPS: Step[] = [
  { path: "/", number: null, title: "Overview", nav: "Overview" },
  { path: "/data", number: 1, title: "Source data", nav: "Data" },
  { path: "/model", number: 2, title: "Semantic model", nav: "Semantic model" },
  { path: "/extract", number: 3, title: "Unstructured → graph", nav: "Text → graph" },
  { path: "/queries", number: 4, title: "Graph queries", nav: "Queries" },
  { path: "/graph-rag", number: 5, title: "Graph-RAG", nav: "Graph-RAG" },
  { path: "/value", number: 6, title: "Business value", nav: "Value" },
];
