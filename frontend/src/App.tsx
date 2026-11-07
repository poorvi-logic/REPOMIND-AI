import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/ui";
import { OverviewPage } from "./pages/OverviewPage";

const ProjectPage = lazy(() => import("./pages/ProjectPage").then((module) => ({ default: module.ProjectPage })));
const ExplorerPage = lazy(() => import("./pages/ExplorerPage").then((module) => ({ default: module.ExplorerPage })));
const IntelligencePage = lazy(() => import("./pages/IntelligencePage").then((module) => ({ default: module.IntelligencePage })));
const DependencyPage = lazy(() => import("./pages/DependencyPage").then((module) => ({ default: module.DependencyPage })));
const RiskPage = lazy(() => import("./pages/RiskPage").then((module) => ({ default: module.RiskPage })));
const AssistantPage = lazy(() => import("./pages/AssistantPage").then((module) => ({ default: module.AssistantPage })));
const McpPage = lazy(() => import("./pages/McpPage").then((module) => ({ default: module.McpPage })));
const JiraPage = lazy(() => import("./pages/JiraPage").then((module) => ({ default: module.JiraPage })));
const LearnPage = lazy(() => import("./pages/LearnPage").then((module) => ({ default: module.LearnPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));

export default function App() {
  return (
    <Suspense fallback={<LoadingBlock label="Loading" />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="analyses/:analysisId" element={<ProjectPage />} />
          <Route path="analyses/:analysisId/explorer" element={<ExplorerPage />} />
          <Route path="analyses/:analysisId/intelligence" element={<IntelligencePage />} />
          <Route path="analyses/:analysisId/dependencies" element={<DependencyPage />} />
          <Route path="analyses/:analysisId/risks" element={<RiskPage />} />
          <Route path="analyses/:analysisId/assistant" element={<AssistantPage />} />
          <Route path="analyses/:analysisId/learn" element={<LearnPage />} />
          <Route path="mcp" element={<McpPage />} />
          <Route path="jira" element={<JiraPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<OverviewPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
