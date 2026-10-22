// Privacy overview (round 2): which personal data the nursery stores, how long, and quick actions.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SettingsEditor } from "../../components/SettingsEditor";
import { Card, ConfirmButton, Kpi, PageHeader, Spinner, useToast } from "../../components/ui";
import { fmtNumber, t } from "../../i18n";

type Overview = {
  customers: number;
  with_phone: number;
  with_email: number;
  addresses: number;
  with_coordinates: number;
  photos: number;
  photos_older: number;
  drafts_with_text: number;
  share_links_active: number;
  settings: Record<string, any>;
};

export function PrivacyPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["privacy-overview"], queryFn: () => api.get<Overview>("/api/privacy/overview") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["privacy-overview"] });
  const cleanUp = async () => {
    const r = await api.post<any>("/api/privacy/retention", { sync: true });
    const res = r.result ?? {};
    toast({ text: t("privacy_page.cleaned", { photos: res.photos ?? 0, customers: res.customers ?? 0, drafts: res.draft_texts ?? 0 }) });
    refresh();
  };
  const removeContacts = async () => {
    const r = await api.post<{ customers: number }>("/api/privacy/remove-contacts");
    toast({ text: t("privacy_page.contacts_removed", { n: r.customers }) });
    refresh();
  };
  const o = q.data;
  const s = o?.settings ?? {};
  return (
    <>
      <PageHeader title={t("nav.privacy")} description={t("privacy_page.description")} />
      {q.isLoading && <Spinner />}
      {o && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 24 }}>
            <Kpi label={t("privacy_page.customers")} value={fmtNumber(o.customers)} sub={t("privacy_page.addresses", { n: o.addresses, geo: o.with_coordinates })} />
            <Kpi label={t("privacy_page.contacts")} value={fmtNumber(Math.max(o.with_phone, o.with_email))} sub={t("privacy_page.contacts_sub", { phone: o.with_phone, email: o.with_email })} />
            <Kpi label={t("privacy_page.photos")} value={fmtNumber(o.photos)} sub={t("privacy_page.photos_sub", { n: o.photos_older, days: s["privacy.photo_retention_days"] })} />
            <Kpi label={t("privacy_page.drafts")} value={fmtNumber(o.drafts_with_text)} sub={t("privacy_page.drafts_sub", { days: s["privacy.draft_text_days"], links: o.share_links_active })} />
          </div>
          <Card title={t("privacy_page.what_title")}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("privacy_page.data")}</th>
                    <th>{t("privacy_page.why")}</th>
                    <th>{t("privacy_page.until")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(["name", "address", "contact", "photos", "messages", "location", "invoices"] as const).map((k) => (
                    <tr key={k}>
                      <td>{t(`privacy_page.rows.${k}.data`)}</td>
                      <td className="small">{t(`privacy_page.rows.${k}.why`)}</td>
                      <td className="small">
                        {t(`privacy_page.rows.${k}.until`, {
                          customer_days: s["privacy.customer_retention_days"],
                          photo_days: s["privacy.photo_retention_days"],
                          draft_days: s["privacy.draft_text_days"],
                          years: s["privacy.invoice_retention_years"],
                          contact: s["privacy.store_contact"] ? t("privacy_page.contact_on") : t("privacy_page.contact_off"),
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: 16, flexWrap: "wrap" }}>
              <button className="btn secondary" onClick={cleanUp}>
                {t("privacy_page.clean_now")}
              </button>
              {(o.with_phone > 0 || o.with_email > 0) && (
                <ConfirmButton className="btn ghost" onConfirm={removeContacts} question={t("privacy_page.remove_contacts_q", { n: Math.max(o.with_phone, o.with_email) })}>
                  {t("privacy_page.remove_contacts")}
                </ConfirmButton>
              )}
            </div>
          </Card>
          <div style={{ marginTop: 24 }}>
            <SettingsEditor scope="tenant" onlyGroups={["privacy"]} compact />
          </div>
        </>
      )}
    </>
  );
}
