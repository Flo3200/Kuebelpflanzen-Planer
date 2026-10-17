// Routes of the feature pages, kept apart from App.tsx so phases can add pages without touching the shell.
import { Route } from "react-router-dom";
import { AdminAIPage, TenantAIPage } from "./pages/admin/AI";
import { SpeciesPage } from "./pages/common/Species";
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
    <Route key="species" path="pflanzenarten" element={<SpeciesPage />} />,
    <Route key="storage" path="lager" element={<StoragePage />} />,
    <Route key="ai" path="ki" element={<TenantAIPage />} />,
    ...extraTenantRoutes(),
  ];
}

export function adminRoutes() {
  return [
    <Route key="ai" path="ki" element={<AdminAIPage />} />,
    <Route key="species" path="pflanzenarten" element={<SpeciesPage admin />} />,
    ...extraAdminRoutes(),
  ];
}
