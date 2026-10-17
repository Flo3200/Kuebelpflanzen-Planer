import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SettingsEditor } from "../../components/SettingsEditor";
import { ConfirmButton, PageHeader, useToast } from "../../components/ui";
import { t } from "../../i18n";

export function PlatformSettingsPage() {
  return (
    <>
      <PageHeader title={t("settings.title")} description={t("settings.admin_description")} />
      <SettingsEditor scope="platform" canEditAdminOnly />
    </>
  );
}

export function TenantSettingsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const resetAll = useMutation({
    mutationFn: () => api.post<{ batch_id: string; count: number }>("/api/settings/reset", { scope: "tenant", all_scopes: true }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast({
        text: t("settings.reset_done", { n: res.count }),
        action: {
          label: t("common.undo"),
          run: async () => {
            await api.post(`/api/audit/batch/${res.batch_id}/undo`);
            qc.invalidateQueries({ queryKey: ["settings"] });
          },
        },
      });
    },
  });
  return (
    <>
      <PageHeader
        title={t("settings.title")}
        description={t("settings.description")}
        actions={
          <span title={t("settings.reset_tenant_help")}>
            <ConfirmButton question={t("settings.reset_tenant_question")} onConfirm={() => resetAll.mutate()}>
              {t("settings.reset_tenant")}
            </ConfirmButton>
          </span>
        }
      />
      <SettingsEditor scope="tenant" />
    </>
  );
}
