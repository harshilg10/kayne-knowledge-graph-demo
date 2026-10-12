import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Extract } from "./pages/Extract";
import { GraphRag } from "./pages/GraphRag";
import { Overview } from "./pages/Overview";
import { Queries } from "./pages/Queries";
import { SemanticModel } from "./pages/SemanticModel";
import { SourceData } from "./pages/SourceData";
import { Value } from "./pages/Value";

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/data" element={<SourceData />} />
        <Route path="/model" element={<SemanticModel />} />
        <Route path="/extract" element={<Extract />} />
        <Route path="/queries" element={<Queries />} />
        <Route path="/graph-rag" element={<GraphRag />} />
        <Route path="/value" element={<Value />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
