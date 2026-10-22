// Navigation of the owner/dispatcher app and the admin app. Items are shown if the user has the
// permission and the optional module of the item is on. Rarely used items (rare) are listed at the very
// bottom of the menu under "Weitere Bereiche", collapsed (wish of the owner: inactive things go down).
export type NavItem = { to: string; label: string; perm?: string; end?: boolean; module?: string; rare?: boolean };
export type NavSection = { label?: string; items: NavItem[] };

export const TENANT_NAV: NavSection[] = [
  { items: [{ to: "/betrieb", label: "nav.overview", end: true, perm: "tenant.view" }] },
  {
    label: "nav.section_intake",
    items: [
      { to: "/betrieb/posteingang", label: "nav.inbox", perm: "drafts.write" },
      { to: "/betrieb/auftraege", label: "nav.orders", perm: "orders.read" },
      { to: "/betrieb/tabellen", label: "nav.tables", perm: "orders.read" },
      { to: "/betrieb/kunden", label: "nav.customers", perm: "customers.read", rare: true },
    ],
  },
  {
    label: "nav.section_planning",
    items: [
      { to: "/betrieb/planung", label: "nav.planning", perm: "planning.read" },
      { to: "/betrieb/meldungen", label: "nav.deviations", perm: "orders.read" },
      { to: "/betrieb/szenarien", label: "nav.scenarios", perm: "scenarios.run", rare: true },
    ],
  },
  {
    label: "nav.section_resources",
    items: [
      { to: "/betrieb/teams", label: "nav.teams", perm: "staff.read" },
      { to: "/betrieb/personal", label: "nav.staff", perm: "staff.read" },
      { to: "/betrieb/fahrzeuge", label: "nav.vehicles", perm: "fleet.read" },
      { to: "/betrieb/verfuegbarkeit", label: "nav.availability", perm: "staff.read" },
      { to: "/betrieb/module", label: "nav.modules", perm: "fleet.read", rare: true },
      { to: "/betrieb/hilfsmittel", label: "nav.equipment", perm: "fleet.read", rare: true },
      { to: "/betrieb/lager", label: "nav.storage", perm: "tenant.view", module: "storage", rare: true },
    ],
  },
  {
    label: "nav.section_analysis",
    items: [
      { to: "/betrieb/kosten", label: "nav.costs", perm: "tenant.view" },
      { to: "/betrieb/preise", label: "nav.pricing", perm: "orders.read", module: "customer_billing", rare: true },
      { to: "/betrieb/formeln", label: "nav.formulas", perm: "formulas.write", rare: true },
      { to: "/betrieb/modell", label: "nav.model", perm: "planning.read", rare: true },
    ],
  },
  {
    label: "nav.section_admin",
    items: [
      { to: "/betrieb/einstellungen", label: "nav.settings", perm: "tenant.settings" },
      { to: "/betrieb/assistent", label: "nav.assistant", perm: "ai.use" },
      { to: "/betrieb/benutzer", label: "nav.users", perm: "tenant.users" },
      { to: "/betrieb/datenschutz", label: "nav.privacy", perm: "customers.read", rare: true },
      { to: "/betrieb/ki", label: "nav.ai_tenant", perm: "ai.use", rare: true },
      { to: "/betrieb/agenten", label: "nav.agents", perm: "tenant.agents", rare: true },
      { to: "/betrieb/abrechnung", label: "nav.billing", perm: "tenant.billing", rare: true },
      { to: "/betrieb/auftraege-im-hintergrund", label: "nav.jobs", perm: "tenant.view", rare: true },
      { to: "/betrieb/protokoll", label: "nav.audit", perm: "audit.read", rare: true },
    ],
  },
];

export const ADMIN_NAV: NavSection[] = [
  { items: [{ to: "/admin", label: "nav.overview", end: true }] },
  {
    label: "nav.platform",
    items: [
      { to: "/admin/betriebe", label: "nav.tenants", perm: "platform.tenants" },
      { to: "/admin/einstellungen", label: "nav.settings", perm: "platform.settings" },
      { to: "/admin/formeln", label: "nav.formulas", perm: "platform.formulas" },
      { to: "/admin/pflanzenarten", label: "nav.species_kb", perm: "platform.species" },
      { to: "/admin/ki", label: "nav.ai", perm: "platform.ai" },
      { to: "/admin/abrechnung", label: "nav.billing", perm: "platform.billing" },
      { to: "/admin/agenten", label: "nav.agents", perm: "platform.agents" },
      { to: "/admin/assistent", label: "nav.assistant", perm: "platform.settings" },
    ],
  },
  {
    label: "nav.section_admin",
    items: [
      { to: "/admin/system", label: "nav.system", perm: "platform.system" },
      { to: "/admin/protokoll", label: "nav.audit", perm: "audit.read" },
      { to: "/admin/konten", label: "nav.admins", perm: "platform.tenants" },
    ],
  },
];
