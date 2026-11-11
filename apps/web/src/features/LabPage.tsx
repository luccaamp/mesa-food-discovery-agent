import { useEffect, useState } from "react";
import { ExternalLink, FlaskConical } from "lucide-react";
import { api, count, type Evaluation, type Meta, type PublicAssistantEvaluation, type ConversationEvaluation } from "../api";

const REPO = "https://github.com/luccaamp/mesa-food-discovery-agent/blob/main/";

export type ComparisonSummary = {
  mode: "planner" | "agent";
  provider: string;
  model: string;
  cases: number;
  passed: number;
  pass_rate: number;
  latency_ms_p50: number | null;
  latency_ms_p95: number | null;
  llm_calls: number;
  tokens_per_model_turn: number | null;
  glossary_fallbacks: number;
};

type Evaluations = {
  reports: Evaluation[];
  conversation_evaluation?: ConversationEvaluation | null;
  public_assistant_evaluation?: PublicAssistantEvaluation | null;
  agent_comparison?: { created_at: string; split: "reserved" | "development"; summaries: ComparisonSummary[] } | null;
};

const LABELS: Record<string, string> = {
  popularity: "Popularidade global",
  repeat: "Repetição pessoal",
  basket_cosine: "Similaridade por cesta",
  lexical: "Busca lexical",
  semantic: "Embeddings E5",
  hybrid: "Busca híbrida",
};
const PROVIDERS: Record<string, string> = { gemini: "Gemini 3.1 Flash-Lite", groq: "Groq · gpt-oss-120b", local: "Qwen 2.5 local" };

function Bars({ report }: { report: Evaluation }) {
  const value = (model: Record<string, any>) => (report.id === "recommendation" ? model.ndcg : model.all.ndcg);
  const best = Math.max(Number.EPSILON, ...Object.values(report.models).map(value));
  return (
    <div>
      {Object.entries(report.models).map(([name, model]) => (
        <div className="bar" key={name}>
          <span>{LABELS[name] ?? name}</span>
          <div className="bar-track">
            <span style={{ width: `${(Math.max(value(model), 0) / best) * 100}%` }} />
          </div>
          <strong>{value(model).toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</strong>
        </div>
      ))}
    </div>
  );
}

export function LabPage({ meta }: { meta: Meta | null }) {
  const [data, setData] = useState<Evaluations | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api<Evaluations>("/v1/evaluations")
      .then(setData)
      .catch(() => setFailed(true));
  }, []);
  const comparison = data?.agent_comparison?.summaries ?? [];
  const bestAgent = comparison.filter((row) => row.mode === "agent").sort((a, b) => b.pass_rate - a.pass_rate)[0];
  const recommendation = data?.reports.find((report) => report.id === "recommendation");
  const retrieval = data?.reports.find((report) => report.id === "retrieval");

  return (
    <div className="page" style={{ display: "grid", gap: 28 }}>
      <header style={{ display: "grid", gap: 8 }}>
        <span className="badge badge-accent" style={{ justifySelf: "start" }}>
          <FlaskConical size={13} /> Laboratório
        </span>
        <h1>Como sabemos que funciona</h1>
        <p className="muted" style={{ maxWidth: "70ch" }}>
          Cada resposta é verificada por código contra o catálogo oficial: ferramenta escolhida, intenção do prato,
          filtros, continuidade da conversa e identidade de cada item. Resultados negativos ficam registrados.
        </p>
      </header>

      <section className="kpis" aria-label="Indicadores">
        <div className="kpi">
          <strong>{meta ? count(meta.products) : "—"}</strong>
          <span>itens reais no catálogo</span>
        </div>
        <div className="kpi">
          <strong>{bestAgent ? `${Math.round(bestAgent.pass_rate * 100)}%` : "—"}</strong>
          <span>cenários aprovados pelo melhor agente</span>
        </div>
        <div className="kpi">
          <strong>{bestAgent?.latency_ms_p50 ? `${(bestAgent.latency_ms_p50 / 1000).toFixed(1)} s` : "—"}</strong>
          <span>latência mediana por turno com modelo</span>
        </div>
        <div className="kpi">
          <strong>14,4%</strong>
          <span>Recall@10 da melhor referência de recomendação</span>
        </div>
      </section>

      {comparison.length > 0 && (
        <section aria-labelledby="comparison-title" style={{ display: "grid", gap: 12 }}>
          <div>
            <h2 id="comparison-title">Planejador × agente, por provedor</h2>
            <p className="muted">
              Os mesmos {comparison[0].cases} cenários{" "}
              {data?.agent_comparison?.split === "reserved"
                ? "reservados, congelados antes de qualquer ajuste do agente,"
                : "de desenvolvimento"}{" "}
              verificados pelas mesmas regras. Planejador: uma chamada estruturada, ferramenta escolhida por código. Agente: o modelo escolhe as
              ferramentas.
            </p>
          </div>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Tabela de comparação">
            <table>
              <thead>
                <tr>
                  <th>Modo</th>
                  <th>Provedor</th>
                  <th className="num">Aprovados</th>
                  <th className="num">p50</th>
                  <th className="num">p95</th>
                  <th className="num">Chamadas</th>
                  <th className="num">Tokens/turno</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((row) => (
                  <tr key={row.mode + row.provider}>
                    <td>{row.mode === "agent" ? "Agente (LangGraph)" : "Planejador"}</td>
                    <td>{PROVIDERS[row.provider] ?? row.provider}</td>
                    <td className="num">
                      {row.passed}/{row.cases}
                    </td>
                    <td className="num">{row.latency_ms_p50 ? `${Math.round(row.latency_ms_p50)} ms` : "—"}</td>
                    <td className="num">{row.latency_ms_p95 ? `${Math.round(row.latency_ms_p95)} ms` : "—"}</td>
                    <td className="num">{row.llm_calls}</td>
                    <td className="num">{row.tokens_per_model_turn ? Math.round(row.tokens_per_model_turn) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Camadas gratuitas dos provedores; latência varia com a carga. Uma repetição por par. Na suíte de
            desenvolvimento, o agente com Groq começou em 35/40 (traduziu “macarrão” como “pasta”); a dica do
            glossário levou a 40/40 antes desta validação.{" "}
            <a href={REPO + "evaluations/results/agent-provider-reserved-v1.json"} target="_blank" rel="noreferrer">
              Dados brutos <ExternalLink size={12} />
            </a>
          </p>
        </section>
      )}

      {recommendation && (
        <section aria-labelledby="rec-title" className="panel" style={{ display: "grid", gap: 10 }}>
          <h2 id="rec-title">Recomendação: prever a próxima cesta</h2>
          <p className="muted">
            Validação temporal com {count(recommendation.users ?? 0)} clientes reais: treino até o dia 61, validação nos dias
            62–75. NDCG@10, quanto maior melhor.
          </p>
          <Bars report={recommendation} />
          <p className="muted" style={{ fontSize: 12 }}>
            Repetir o que a pessoa já pediu é a referência mais forte. O site não identifica clientes, então serve
            associação entre itens e popularidade.
          </p>
        </section>
      )}

      {retrieval && (
        <section aria-labelledby="ret-title" className="panel" style={{ display: "grid", gap: 10 }}>
          <h2 id="ret-title">Busca: embeddings não venceram</h2>
          <p className="muted">
            Piloto em {count(retrieval.products ?? 0)} produtos. O E5 multilíngue não superou a busca lexical com glossário
            e não foi promovido. Rótulos automáticos por regras de nome.
          </p>
          <Bars report={retrieval} />
        </section>
      )}

      <section className="prose" aria-label="Mais evidências">
        <h2>Outras verificações</h2>
        {data?.public_assistant_evaluation && (
          <p>
            Aceitação no site publicado: {data.public_assistant_evaluation.passed}/{data.public_assistant_evaluation.total}{" "}
            tarefas com {data.public_assistant_evaluation.model}, {data.public_assistant_evaluation.catalog_items_checked}{" "}
            itens conferidos no catálogo.
          </p>
        )}
        {data?.conversation_evaluation && (
          <p>
            Conversas roteirizadas no modelo local: {data.conversation_evaluation.passed}/
            {data.conversation_evaluation.episodes} episódios aprovados em {data.conversation_evaluation.profiles} perfis.
          </p>
        )}
        <p>
          Contingência: 52/52 cenários com o provedor fora do ar continuam respondendo pelo glossário, com cada item
          conferido. Juízes LLM de relevância foram testados e reprovados na calibração; nenhuma nota deles aprova o
          produto.
        </p>
        <p>
          <a href={REPO + "docs/AUTOMATED_EVALUATION.md"} target="_blank" rel="noreferrer">
            Protocolo de avaliação <ExternalLink size={12} />
          </a>{" "}
          ·{" "}
          <a href={REPO + "docs/ARCHITECTURE.md"} target="_blank" rel="noreferrer">
            Arquitetura <ExternalLink size={12} />
          </a>
        </p>
        {failed && <p className="notice notice-warning">Os relatórios não puderam ser carregados agora.</p>}
      </section>
    </div>
  );
}
