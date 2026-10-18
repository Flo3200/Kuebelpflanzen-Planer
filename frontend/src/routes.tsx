// Routes of the feature pages, kept apart from App.tsx so phases can add pages without touching the shell.
import { Route } from "react-router-dom";
import { AdminAIPage, TenantAIPage } from "./pages/admin/AI";
import { AgentsPage } from "./pages/common/Agents";
import { AssistantPage } from "./pages/common/Assistant";
import { AdminBillingPage, TenantBillingPage } from "./pages/common/Billing";
import { FormulasPage } from "./pages/common/Formulas";
import { SpeciesPage } from "./pages/common/Species";
import { DeviationsPage } from "./pages/tenant/Deviations";
import { LoadPlanPage } from "./pages/tenant/LoadPlan";
import { ModelPage } from "./pages/tenant/Model";
import { PlanningPage } from "./pages/tenant/Planning";
import { PricingPage } from "./pages/tenant/Pricing";
import { ScenariosPage } from "./pages/tenant/Scenarios";
import { CostsPage } from "./pages/tenant/Costs";
import { ModulesPage } from "./pages/tenant/Modules";
import { DraftReviewPage, InboxPage } from "./pages/tenant/Inbox";
import { CustomerDetailPage, CustomersPage, OrderDetailPage, OrdersPage } from "./pages/tenant/Orders";
import { AvailabilityPage, EquipmentPage, StaffPage, StoragePage, TeamsPage, VehiclesPage } from "./pages/tenant/Resources";
import { extraTenantRoutes, extraAdminRoutes } from "./routesLater";

export function tenantRoutes() {
  return [
    <Route key="inbox" path="posteingang" element={<InboxPage />} />,
    <Route key="draft" path="posteingang/:id" element={<DraftReviewPage />} />,
    <Route key="customers" path="kunden" element={<CustomersPage />} />,
    <Route key="customer" path="kunden/:id" element={<CustomerDetailPage />} />,
    <Route key="orders" path="auftraege" element={<OrdersPage />} />,
    <Route key="order" path="auftraege/:id" element={<OrderDetailPage />} />,
    <Route key="staff" path="personal" element={<StaffPage />} />,
    <Route key="teams" path="teams" element={<TeamsPage />} />,
    <Route key="vehicles" path="fahrzeuge" element={<VehiclesPage />} />,
    <Route key="equipment" path="hilfsmittel" element={<EquipmentPage />} />,
    <Route key="availability" path="verfuegbarkeit" element={<AvailabilityPage />} />,
    <Route key="storage" path="lager" element={<StoragePage />} />,
    <Route key="ai" path="ki" element={<TenantAIPage />} />,
    <Route key="pricing" path="preise" element={<PricingPage />} />,
    <Route key="costs" path="kosten" element={<CostsPage />} />,
    <Route key="modules" path="module" element={<ModulesPage />} />,
    <Route key="formulas" path="formeln" element={<FormulasPage />} />,
    <Route key="planning" path="planung" element={<PlanningPage />} />,
    <Route key="loadplan" path="planung/touren/:id/ladeplan" element={<LoadPlanPage />} />,
    <Route key="scenarios" path="szenarien" element={<ScenariosPage />} />,
    <Route key="deviations" path="meldungen" element={<DeviationsPage />} />,
    <Route key="model" path="modell" element={<ModelPage />} />,
    <Route key="agents" path="agenten" element={<AgentsPage />} />,
    <Route key="billing" path="abrechnung" element={<TenantBillingPage />} />,
    <Route key="assistant" path="assistent" element={<AssistantPage />} />,
    ...extraTenantRoutes(),
  ];
}

export function adminRoutes() {
  return [
    <Route key="ai" path="ki" element={<AdminAIPage />} />,
    <Route key="species" path="pflanzenarten" element={<SpeciesPage admin />} />,
    <Route key="formulas" path="formeln" element={<FormulasPage />} />,
    <Route key="agents" path="agenten" element={<AgentsPage admin />} />,
    <Route key="billing" path="abrechnung" element={<AdminBillingPage />} />,
    <Route key="assistant" path="assistent" element={<AssistantPage />} />,
    ...extraAdminRoutes(),
  ];
}
