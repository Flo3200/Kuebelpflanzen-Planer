// AI discussion about a formula (round 2): two models (e.g. ChatGPT and Claude) discuss in turns with the
// real measurements; the final proposal is checked and can be adopted as a new formula version.
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Card, ErrorBox, Spinner, useToast } from "../../components/ui";
import { fmtDate, fmtNumber, t } from "../../i18n";
import { JobStatus, useJob } from "./Jobs";

type Model = { id: string; label: string; provider: string; kind: string; ready: boolean };

/** Ready model of the wanted provider (ChatGPT for one side, Claude for the other), else any ready one. */
function pick(models: Model[], kind: string, other?: string): string {
  const ready = models.filter((m) => m.ready);
  return (ready.find((m) => m.kind === kind && m.id !== other) ?? ready.find((m) => m.id !== other) ?? ready[0] ?? models[0])?.id ?? "";
}

export function FormulaDebateCard({ formulaKey }: { formulaKey: "time" | "unload" | "price" }) {
  const qc = useQueryClient();
  const toast = useToast();
  const models = useQuery({ queryKey: ["debate-models"], queryFn: () => api.get<Model[]>("/api/formula-debates/models") });
  const list = useQuery({ queryKey: ["debates"], queryFn: () => api.get<any[]>("/api/formula-debates") });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [rounds, setRounds] = useState(2);
  const [question, setQuestion] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const ms = models.data ?? [];
    if (ms.length && !a) {
      const first = pick(ms, "openai");
      setA(first);
      setB(pick(ms, "anthropic", first));
    }
  }, [models.data, a]);
  const open = (list.data ?? []).find((d) => d.id === openId) ?? null;
  const detail = useQuery({
    queryKey: ["debate", openId],
    queryFn: () => api.get<any>(`/api/formula-debates/${openId}`),
    enabled: !!openId,
    refetchInterval: (q) => (["new", "running"].includes(q.state.data?.status) ? 2000 : false),
  });
  const d = detail.data ?? open;
  const job = useJob(d && ["new", "running"].includes(d.status) ? d.job_id : null);
  if (formulaKey === "price") return null;
  const start = async () => {
    setError(null);
    try {
      const r = await api.post<any>("/api/formula-debates", { formula_key: formulaKey, model_a_id: a || null, model_b_id: b || null, n_rounds: rounds, question: question || null });
      setOpenId(r.id);
      qc.invalidateQueries({ queryKey: ["debates"] });
    } catch (e) {
      setError(e);
    }
  };
  const adopt = async () => {
    setError(null);
    try {
      const r = await api.post<any>(`/api/formula-debates/${d.id}/adopt`);
      toast({ text: t("debate.adopted", { v: r.version }) });
      qc.invalidateQueries({ queryKey: ["formulas"] });
      qc.invalidateQueries({ queryKey: ["debate", d.id] });
    } catch (e) {
      setError(e);
    }
  };
  const ev = d?.evaluation ?? {};
  const row = (label: string, m: any) =>
    m && (
      <tr>
        <td>{label}</td>
        <td className="num">{fmtNumber(m.mae, 1)}</td>
        <td className="num">{fmtNumber(m.mape, 1)} %</td>
        <td className="num">{fmtNumber(m.bias, 1)}</td>
      </tr>
    );
  return (
    <Card title={t("debate.title")}>
      <p className="small muted" style={{ marginTop: 0 }}>{t("debate.intro")}</p>
      <div className="form-grid">
        {(["a", "b"] as const).map((side) => (
          <div className="field" key={side}>
            <label htmlFor={`deb-${side}`}>{t(`debate.model_${side}`)}</label>
            <select id={`deb-${side}`} className="input" value={side === "a" ? a : b} onChange={(e) => (side === "a" ? setA(e.target.value) : setB(e.target.value))}>
              {(models.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} ({m.provider}){m.ready ? "" : ` – ${t("debate.no_key")}`}
                </option>
              ))}
            </select>
          </div>
        ))}
        <div className="field">
          <label htmlFor="deb-rounds">{t("debate.rounds")}</label>
          <select id="deb-rounds" className="input" value={rounds} onChange={(e) => setRounds(Number(e.target.value))}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {t("debate.rounds_n", { n, turns: n * 2 })}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="deb-q">{t("debate.question")}</label>
        <input id="deb-q" className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t("debate.question_placeholder")} />
      </div>
      <div className="row between" style={{ marginTop: 8 }}>
        <span className="xs muted">{t("debate.privacy")}</span>
        <button className="btn" onClick={start}>
          {t("debate.start")}
        </button>
      </div>
      <ErrorBox error={error} />
      {(list.data ?? []).length > 0 && (
        <div className="chip-list" style={{ marginTop: 12 }}>
          {(list.data ?? []).slice(0, 8).map((x) => (
            <button key={x.id} className={`col-chip ${x.id === openId ? "on" : ""}`} onClick={() => setOpenId(x.id)}>
              {fmtDate(x.created_at, true)} · {x.model_a ?? "?"} / {x.model_b ?? "?"}
              {x.adopted_version_id && " ✓"}
            </button>
          ))}
        </div>
      )}
      {d && (
        <div className="stack" style={{ marginTop: 16 }}>
          {["new", "running"].includes(d.status) && (job.data ? <JobStatus job={job.data} /> : <Spinner label={t("debate.running")} />)}
          {d.status === "failed" && <div className="alert error">{d.error ?? t("errors.generic")}</div>}
          {(d.rounds ?? []).map((r: any, i: number) => (
            <div key={i} className={`debate-turn side-${r.speaker}`}>
              <div className="xs muted">
                {r.model} {r.agree && <Badge tone="green">{t("debate.agrees")}</Badge>}
              </div>
              <div className="small" style={{ whiteSpace: "pre-wrap" }}>{r.text}</div>
              {r.formula && (
                <pre className="xs debate-formula">
                  {r.formula.expressions.map((e: any) => `${e.name} (${e.level}) = ${e.expr}`).join("\n")}
                </pre>
              )}
            </div>
          ))}
          {d.status === "done" && (
            <Card title={t("debate.proposal")}>
              {d.proposal?.valid ? (
                <>
                  <pre className="xs debate-formula">{(d.proposal.expressions ?? []).map((e: any) => `${e.name} (${e.level}) = ${e.expr}`).join("\n")}</pre>
                  {ev.n > 0 ? (
                    <table className="table" style={{ marginTop: 8 }}>
                      <thead>
                        <tr>
                          <th>{t("debate.eval_on", { n: ev.n })}</th>
                          <th className="num">{t("debate.mae")}</th>
                          <th className="num">{t("debate.mape")}</th>
                          <th className="num">{t("debate.bias")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {row(t("debate.current"), ev.current)}
                        {row(t("debate.current_fitted"), ev.current_fitted)}
                        {row(t("debate.proposed_start"), ev.proposed_start)}
                        {row(t("debate.proposed_fitted"), ev.proposed_fitted)}
                      </tbody>
                    </table>
                  ) : (
                    <p className="small muted">{t("debate.no_measurements")}</p>
                  )}
                  <div className="row" style={{ marginTop: 8 }}>
                    {d.adopted_version_id ? (
                      <Badge tone="green">{t("debate.is_adopted")}</Badge>
                    ) : (
                      <button className="btn secondary" onClick={adopt}>
                        {t("debate.adopt")}
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <div className="alert warn small">
                  {t("debate.invalid")}: {(d.proposal?.problems ?? []).map((p: any) => p.detail).join("; ")}
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </Card>
  );
}
