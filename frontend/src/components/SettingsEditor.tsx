// Generic settings editor generated from the settings registry. Shows origin and inherited value,
// supports reset per value / group / level and one-click undo.
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { t, fmtNumber } from "../i18n";
import { Badge, ConfirmButton, ErrorBox, Segmented, Spinner, useToast } from "./ui";

export type SettingValue = {
  key: string;
  group: string;
  type: string;
  unit: string | null;
  min: number | null;
  max: number | null;
  choices: string[] | null;
  choices_source: string | null;
  important: boolean;
  admin_only: boolean;
  /** false if the setting belongs to an optional module that is off (then it is not shown) */
  module_active?: boolean;
  label: string;
  help: string;
  value: any;
  origin: string;
  origin_is_global: boolean;
  overridden_here: boolean;
  inherited_value: any;
  inherited_origin: string;
  default: any;
};

type Registry = {
  groups: { key: string; label: string }[];
  settings: { key: string; choice_labels: Record<string, string> }[];
  origins: Record<string, string>;
};

export function useRegistry() {
  return useQuery({ queryKey: ["settings-registry"], queryFn: () => api.get<Registry>("/api/settings/registry"), staleTime: Infinity });
}

function originTone(origin: string): "green" | "terra" | "blue" | undefined {
  if (origin === "default") return undefined;
  if (origin === "platform") return "blue";
  if (origin === "tenant") return "green";
  return "terra";
}

export function formatValue(v: SettingValue | { type: string; unit: string | null }, value: any, choiceLabels?: Record<string, string>): string {
  if (value === null || value === undefined) return "–";
  if (v.type === "bool") return value ? t("common.yes") : t("common.no");
  if (v.type === "enum") return choiceLabels?.[value] ?? String(value);
  if (v.type === "json") return JSON.stringify(value).slice(0, 60);
  if (v.type === "float") return `${fmtNumber(value, Number.isInteger(value) ? 0 : 2)}${v.unit ? " " + v.unit : ""}`;
  if (v.type === "int") return `${fmtNumber(value)}${v.unit ? " " + v.unit : ""}`;
  return String(value) || "–";
}

export function SettingsEditor(props: {
  scope: string;
  objectId?: string;
  tenantId?: string;
  onlyGroups?: string[];
  compact?: boolean;
  canEditAdminOnly?: boolean;
}) {
  const { scope, objectId, tenantId } = props;
  const qc = useQueryClient();
  const toast = useToast();
  const registry = useRegistry();
  const [mode, setMode] = useState<"simple" | "expert">(props.compact ? "expert" : "simple");
  const [group, setGroup] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const queryKey = ["settings", scope, objectId ?? null, tenantId ?? null];
  const query = useQuery({
    queryKey,
    queryFn: () =>
      api.get<{ values: SettingValue[]; groups: { key: string; label: string }[] }>("/api/settings", {
        scope,
        object_id: objectId,
        tenant_id: tenantId,
      }),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };

  const undo = async (url: string) => {
    await api.post(url);
    invalidate();
    toast({ text: t("settings.undone") });
  };

  const save = useMutation({
    mutationFn: (p: { key: string; value: any }) =>
      api.put<{ audit_id: string }>("/api/settings", { scope, key: p.key, value: p.value, object_id: objectId, tenant_id: tenantId }),
    onSuccess: (res) => {
      invalidate();
      toast({ text: t("settings.saved"), action: { label: t("common.undo"), run: () => undo(`/api/audit/${res.audit_id}/undo`) } });
    },
    onError: (e: Error) => toast({ text: e.message, tone: "error" }),
  });

  const reset = useMutation({
    mutationFn: (p: { key?: string; group?: string; all_scopes?: boolean }) =>
      api.post<{ batch_id: string; count: number }>("/api/settings/reset", { scope, object_id: objectId, tenant_id: tenantId, ...p }),
    onSuccess: (res) => {
      invalidate();
      toast({
        text: t("settings.reset_done", { n: res.count }),
        action: res.count ? { label: t("common.undo"), run: () => undo(`/api/audit/batch/${res.batch_id}/undo`) } : undefined,
      });
    },
    onError: (e: Error) => toast({ text: e.message, tone: "error" }),
  });

  const values = (query.data?.values ?? []).filter((v) => v.module_active !== false);
  const groups = (query.data?.groups ?? []).filter(
    (g) => values.some((v) => v.group === g.key) && (!props.onlyGroups || props.onlyGroups.includes(g.key)),
  );
  const activeGroup = group && groups.some((g) => g.key === group) ? group : groups[0]?.key;
  const choiceLabels = useMemo(() => {
    const m: Record<string, Record<string, string>> = {};
    registry.data?.settings.forEach((s) => (m[s.key] = s.choice_labels));
    return m;
  }, [registry.data]);
  const origins = registry.data?.origins ?? {};

  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorBox error={query.error} />;

  const visible = values.filter((v) => {
    if (props.onlyGroups && !props.onlyGroups.includes(v.group)) return false;
    if (filter) {
      const f = filter.toLowerCase();
      return v.label.toLowerCase().includes(f) || v.help.toLowerCase().includes(f) || v.key.includes(f);
    }
    if (v.group !== activeGroup) return false;
    return mode === "expert" || v.important || v.overridden_here;
  });
  const overriddenCount = (g: string) => values.filter((v) => v.group === g && v.overridden_here).length;

  return (
    <div className="stack lg">
      <div className="row between">
        <div className="row">
          <Segmented
            label={t("settings.view")}
            value={mode}
            onChange={setMode}
            items={[
              { key: "simple", label: t("settings.simple") },
              { key: "expert", label: t("settings.expert") },
            ]}
          />
          <input
            className="input"
            style={{ width: 240 }}
            placeholder={t("settings.search")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label={t("settings.search")}
          />
        </div>
        <ConfirmButton
          question={scope === "tenant" ? t("settings.reset_all_question") : t("settings.reset_level_question")}
          onConfirm={() => reset.mutate(scope === "tenant" ? { all_scopes: false } : {})}
        >
          {t("settings.reset_level")}
        </ConfirmButton>
      </div>
      <div className={props.compact ? "stack" : "settings-layout"}>
        {!props.compact && !filter && (
          <nav className="settings-nav" aria-label={t("settings.groups")}>
            {groups.map((g) => (
              <button key={g.key} className={g.key === activeGroup ? "active" : ""} onClick={() => setGroup(g.key)}>
                <span>{g.label}</span>
                {overriddenCount(g.key) > 0 && <Badge tone="terra">{overriddenCount(g.key)}</Badge>}
              </button>
            ))}
          </nav>
        )}
        {props.compact && !filter && groups.length > 1 && (
          <div className="segmented" style={{ alignSelf: "flex-start", flexWrap: "wrap" }}>
            {groups.map((g) => (
              <button key={g.key} className={g.key === activeGroup ? "active" : ""} onClick={() => setGroup(g.key)}>
                {g.label}
              </button>
            ))}
          </div>
        )}
        <div className="card">
          {!filter && activeGroup && (
            <div className="card-head">
              <h3>{groups.find((g) => g.key === activeGroup)?.label}</h3>
              {overriddenCount(activeGroup) > 0 && (
                <button className="btn small ghost" onClick={() => reset.mutate({ group: activeGroup })}>
                  {t("settings.reset_group")}
                </button>
              )}
            </div>
          )}
          {visible.length === 0 && <p className="muted">{t("settings.none_visible")}</p>}
          {visible.map((v) => (
            <SettingRow
              key={v.key}
              v={v}
              scope={scope}
              origins={origins}
              choiceLabels={choiceLabels[v.key]}
              readOnly={v.admin_only && !props.canEditAdminOnly && scope !== "platform"}
              onSave={(value) => save.mutate({ key: v.key, value })}
              onReset={() => reset.mutate({ key: v.key })}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function SettingRow(props: {
  v: SettingValue;
  scope: string;
  origins: Record<string, string>;
  choiceLabels?: Record<string, string>;
  readOnly: boolean;
  onSave: (value: any) => void;
  onReset: () => void;
}) {
  const { v } = props;
  const [draft, setDraft] = useState<any>(undefined);
  const [error, setError] = useState<string | null>(null);
  const current = draft === undefined ? v.value : draft;
  const dirty = draft !== undefined && JSON.stringify(draft) !== JSON.stringify(v.value);
  const id = `setting-${v.key}`;

  const commit = () => {
    if (!dirty) return;
    let value = draft;
    if (v.type === "json") {
      try {
        value = JSON.parse(draft);
      } catch {
        setError(t("settings.invalid_json"));
        return;
      }
    }
    setError(null);
    props.onSave(value);
    setDraft(undefined);
  };

  let input;
  if (v.type === "bool") {
    input = (
      <label className="checkbox">
        <input id={id} type="checkbox" checked={!!current} disabled={props.readOnly} onChange={(e) => props.onSave(e.target.checked)} />
        <span>{current ? t("common.yes") : t("common.no")}</span>
      </label>
    );
  } else if (v.choices_source === "ai_models") {
    input = <AIModelSelect id={id} value={current} disabled={props.readOnly} onChange={(value) => props.onSave(value)} />;
  } else if (v.type === "enum" && v.choices) {
    input = (
      <select id={id} className="input" value={current} disabled={props.readOnly} onChange={(e) => props.onSave(e.target.value)}>
        {v.choices.map((c) => (
          <option key={c} value={c}>
            {props.choiceLabels?.[c] ?? c}
          </option>
        ))}
      </select>
    );
  } else if (v.type === "json" || v.type === "text") {
    const text = draft !== undefined ? draft : v.type === "json" ? JSON.stringify(v.value, null, 2) : (v.value ?? "");
    input = (
      <textarea
        id={id}
        className={`input mono ${error ? "invalid" : ""}`}
        rows={v.type === "json" ? 5 : 4}
        value={text}
        disabled={props.readOnly}
        onChange={(e) => setDraft(e.target.value)}
      />
    );
  } else {
    const isNum = v.type === "int" || v.type === "float";
    input = (
      <div className={v.unit ? "input-unit" : undefined}>
        <input
          id={id}
          className="input num"
          type={v.type === "time" ? "time" : isNum ? "number" : "text"}
          step={v.type === "float" ? "any" : undefined}
          min={v.min ?? undefined}
          max={v.max ?? undefined}
          value={current ?? ""}
          disabled={props.readOnly}
          onChange={(e) => setDraft(isNum ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
        />
        {v.unit && <span className="unit">{v.unit}</span>}
      </div>
    );
  }

  const originText = v.origin_is_global ? t("settings.origin_global_object") : (props.origins[v.origin] ?? v.origin);
  return (
    <div className={`setting-row ${v.overridden_here ? "overridden" : ""}`}>
      <div>
        <label htmlFor={id} className="setting-label">
          {v.label}
        </label>
        {v.help && <div className="setting-help">{v.help}</div>}
        <div className="origin row" style={{ gap: 6 }}>
          <Badge tone={originTone(v.origin)}>{originText}</Badge>
          {v.overridden_here && (
            <span className="xs muted">
              {t("settings.inherited")}: {formatValue(v, v.inherited_value, props.choiceLabels)} ({props.origins[v.inherited_origin] ?? v.inherited_origin})
            </span>
          )}
          {v.admin_only && <Badge>{t("settings.admin_only")}</Badge>}
        </div>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        {input}
        {error && <span className="error-text xs">{error}</span>}
        {(v.min !== null || v.max !== null) && v.type !== "bool" && (
          <span className="xs faint">
            {t("settings.range", { min: v.min ?? "–", max: v.max ?? "–" })}
          </span>
        )}
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        {dirty && (v.type === "json" || v.type === "text") && (
          <button className="btn small" onClick={commit}>
            {t("common.save")}
          </button>
        )}
        {v.overridden_here && !props.readOnly && (
          <button className="btn small ghost" onClick={props.onReset} title={t("settings.reset_value_help")}>
            {t("settings.reset_value")}
          </button>
        )}
      </div>
    </div>
  );
}

function AIModelSelect(props: { id: string; value: string; disabled: boolean; onChange: (v: string) => void }) {
  const q = useQuery({ queryKey: ["ai-models"], queryFn: () => api.get<any[]>("/api/ai/models"), staleTime: 60_000 });
  return (
    <select id={props.id} className="input" value={props.value ?? ""} disabled={props.disabled} onChange={(e) => props.onChange(e.target.value)}>
      <option value="">{t("settings.ai_default_model")}</option>
      {(q.data ?? []).map((m) => (
        <option key={m.id} value={m.id}>
          {m.label} ({m.provider_name})
        </option>
      ))}
    </select>
  );
}
