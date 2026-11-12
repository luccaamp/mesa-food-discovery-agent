import { useEffect, useState } from "react";
import { ExternalLink, FlaskConical, Send } from "lucide-react";
import { api, count, type Meta } from "../api";

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

export type RedTeamSummary = {
  provider: string;
  model: string;
  cases: number;
  passed: number;
  model_exercised: number;
  model_fallbacks: number;
  report: string;
  by_risk: { owasp: string; cases: number; passed: number }[];
};

const OWASP: Record<string, string> = {
  LLM01: "Injeção de prompt",
  LLM02: "Vazamento de dados sensíveis",
  LLM05: "Saída sem tratamento",
  LLM06: "Agência excessiva",
  LLM07: "Vazamento do prompt de sistema",
  LLM09: "Desinformação",
};

const BOT = "https://t.me/mesa_food_discovery_bot";

type SegmentScores = Record<string, number> & { customers: number };
type Discovery = {
  stage: "validation" | "final_test";
  report: string;
  targets: { customers: number; segments: Record<string, number> };
  restaurants: Record<string, Record<string, SegmentScores>>;
  items: Record<string, Record<string, SegmentScores>>;
};
const SEGMENTS: [string, string][] = [
  ["all", "Todos"],
  ["cold", "Cliente novo"],
  ["warm_new", "Recorrente, restaurante novo"],
  ["warm_repeat", "Recorrente, volta ao restaurante"],
];
const DISCOVERY_MODELS: Record<string, string> = {
  popular_global: "Mais pedidos da cidade, período todo",
  random: "Sorteio de 10 restaurantes (acaso)",
  popular_city_recent: "Mais pedidos da cidade, últimas 2 semanas",
  popular_region: "Mais pedidos da região",
  popular_region_slot: "Região × horário",
  repeat_then_global: "Repetição + cidade (baseline v2)",
  repeat_then_region_slot: "Repetição + região × horário",
  repeat_6_plus_discovery_4: "Repetição 6 + descoberta 4",
  ranker: "Ranker LightGBM",
  ranker_6_plus_discovery_4: "Ranker 6 + descoberta 4",
  ranker_items: "Itens dos restaurantes do ranker",
};
const pct = (value: number) =>
  `${(value * 100).toLocaleString("pt-BR", { maximumFractionDigits: value < 0.01 ? 2 : 1 })}%`;

function DiscoveryTable({ label, rows, metric }: { label: string; rows: Record<string, Record<string, SegmentScores>>; metric: string }) {
  const best = Object.fromEntries(
    SEGMENTS.map(([segment]) => [segment, Math.max(...Object.values(rows).map((row) => row[segment][metric]))]),
  );
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={label}>
      <table>
        <thead>
          <tr>
            <th>Modelo</th>
            {SEGMENTS.map(([segment, name]) => (
              <th className="num" key={segment}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.keys(DISCOVERY_MODELS).filter((model) => rows[model]).map((model) => [model, rows[model]] as const).map(([model, row]) => (
            <tr key={model}>
              <td>{DISCOVERY_MODELS[model] ?? model}</td>
              {SEGMENTS.map(([segment]) => (
                <td className="num" key={segment}>
                  {row[segment][metric] === best[segment] ? <strong>{pct(row[segment][metric])}</strong> : pct(row[segment][metric])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ArmScore = { mean: number; ci95: [number, number] | null };
type ArmScores = Record<string, ArmScore> & { cases: number };
type AgentDiscovery = {
  report: string;
  cases: { new_customers: number; llm_sample: number };
  arms: { all_new_customers: Record<string, ArmScores>; llm_sample: Record<string, ArmScores> };
};
const AGENT_ARMS: Record<string, string> = {
  home: "Home: região × horário (ignora a mensagem)",
  search_pt: "Busca com a culinária em português",
  search_en: "Busca com a palavra do catálogo (inglês)",
  search_pt_local: "Busca em português, reordenada pela região",
  search_en_local: "Busca em inglês, reordenada pela região",
  agent: "Agente (LLM com ferramentas)",
  agent_local: "Agente, reordenado pela região",
};

function AgentTable({ data }: { data: AgentDiscovery }) {
  const all = data.arms.all_new_customers;
  const sample = data.arms.llm_sample;
  const arms = Object.keys(AGENT_ARMS).filter((arm) => all[arm] || sample[arm]);
  const cell = (score?: ArmScore) => (score ? pct(score.mean) : "—");
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Tabela do experimento do agente">
      <table>
        <thead>
          <tr>
            <th>Braço</th>
            <th className="num">Restaurante real entre 5, todos os novos</th>
            <th className="num">Restaurante real entre 5, amostra com LLM</th>
            <th className="num">Itens da culinária pedida</th>
            <th className="num">Sem resposta</th>
          </tr>
        </thead>
        <tbody>
          {arms.map((arm) => (
            <tr key={arm}>
              <td>{AGENT_ARMS[arm]}</td>
              <td className="num">{cell(all[arm]?.restaurant_hit)}</td>
              <td className="num">{cell(sample[arm]?.restaurant_hit)}</td>
              <td className="num">{cell((sample[arm] ?? all[arm])?.cuisine_match)}</td>
              <td className="num">{cell((sample[arm] ?? all[arm])?.empty)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Retrieval = { products: number; queries: number; report: string; models: Record<string, { all: { ndcg: number } }> };
type Evaluations = {
  red_team?: RedTeamSummary[];
  discovery?: Discovery | null;
  agent_discovery?: AgentDiscovery | null;
  retrieval?: Retrieval | null;
  agent_comparison?: { created_at: string; split: "reserved" | "development"; summaries: ComparisonSummary[] } | null;
};

const LABELS: Record<string, string> = {
  lexical: "Busca lexical",
  semantic: "Embeddings E5",
  hybrid: "Busca híbrida",
};
const PROVIDERS: Record<string, string> = { gemini: "Gemini 3.1 Flash-Lite", groq: "Groq · gpt-oss-120b" };

function Bars({ report }: { report: Retrieval }) {
  const value = (model: { all: { ndcg: number } }) => model.all.ndcg;
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
  const redTeam = data?.red_team ?? [];
  const risks = Array.from(new Set(redTeam.flatMap((run) => run.by_risk.map((risk) => risk.owasp)))).sort();
  const discovery = data?.discovery;
  const agentDiscovery = data?.agent_discovery;
  const retrieval = data?.retrieval;

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
          <strong>{discovery ? pct(discovery.restaurants.popular_region_slot.cold["hit@10"]) : "—"}</strong>
          <span>
            restaurante certo entre 10 para cliente novo, com região × horário (mais pedidos recentes da cidade:{" "}
            {discovery ? pct(discovery.restaurants.popular_city_recent.cold["hit@10"]) : "—"})
          </span>
        </div>
      </section>

      {discovery && (
        <section aria-labelledby="discovery-title" style={{ display: "grid", gap: 12 }}>
          <div>
            <h2 id="discovery-title">O que mostrar na home: região e horário contam</h2>
            <p className="muted">
              {count(discovery.targets.customers)} próximos pedidos reais{" "}
              {discovery.stage === "final_test"
                ? "do teste oficial do DHRD (dias 76–90), avaliado uma única vez"
                : "da validação (dias 62–75)"}
              . Restaurantes: o restaurante do pedido real está entre os 10 mostrados (Hit@10).
            </p>
          </div>
          <DiscoveryTable label="Tabela de restaurantes" rows={discovery.restaurants} metric="hit@10" />
          <p className="muted">Itens: fração dos itens do pedido real entre os 10 sugeridos (Recall@10).</p>
          <DiscoveryTable label="Tabela de itens" rows={discovery.items} metric="recall@10" />
          <p className="muted" style={{ fontSize: 12 }}>
            Protocolo congelado antes de rodar.{" "}
            <a href={REPO + "docs/EXPERIMENT_DISCOVERY.md"} target="_blank" rel="noreferrer">
              Experimento 004 <ExternalLink size={12} />
            </a>{" "}
            ·{" "}
            <a href={REPO + "evaluations/results/" + discovery.report} target="_blank" rel="noreferrer">
              dados brutos <ExternalLink size={12} />
            </a>
          </p>
        </section>
      )}

      {agentDiscovery && (
        <section aria-labelledby="agent-title" style={{ display: "grid", gap: 12 }}>
          <div>
            <h2 id="agent-title">O agente ajuda o cliente novo a achar o que ele pediu?</h2>
            <p className="muted">
              Para cada cliente novo do teste oficial, uma mensagem gerada por código diz a culinária do pedido real
              (sem nome de item). {count(agentDiscovery.cases.new_customers)} clientes nos braços sem LLM;{" "}
              {agentDiscovery.cases.llm_sample} numa amostra com o agente, pela cota do provedor.
            </p>
          </div>
          <AgentTable data={agentDiscovery} />
          <p className="muted" style={{ fontSize: 12 }}>
            <a href={REPO + "docs/EXPERIMENT_AGENT.md"} target="_blank" rel="noreferrer">
              Experimento do agente <ExternalLink size={12} />
            </a>{" "}
            ·{" "}
            <a href={REPO + "evaluations/results/" + agentDiscovery.report} target="_blank" rel="noreferrer">
              dados brutos <ExternalLink size={12} />
            </a>
          </p>
        </section>
      )}


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

      {redTeam.length > 0 && (
        <section aria-labelledby="redteam-title" style={{ display: "grid", gap: 12 }}>
          <div>
            <h2 id="redteam-title">Red team: OWASP Top 10 para LLMs</h2>
            <p className="muted">
              {redTeam[0].cases} ataques contra o agente real: injeção direta e indireta (texto malicioso dentro do
              catálogo), vazamento do prompt, dados pessoais, ferramentas inexistentes, links e promessas sobre
              alergênicos. Cada resposta é julgada por código, nunca por outro modelo.
            </p>
          </div>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Tabela do red team">
            <table>
              <thead>
                <tr>
                  <th>Risco</th>
                  {redTeam.map((run) => (
                    <th className="num" key={run.provider}>
                      {PROVIDERS[run.provider] ?? run.provider}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {risks.map((owasp) => (
                  <tr key={owasp}>
                    <td>
                      {owasp} · {OWASP[owasp] ?? owasp}
                    </td>
                    {redTeam.map((run) => {
                      const risk = run.by_risk.find((row) => row.owasp === owasp);
                      return (
                        <td className="num" key={run.provider}>
                          {risk ? `${risk.passed}/${risk.cases}` : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr>
                  <td>
                    <strong>Total</strong>
                  </td>
                  {redTeam.map((run) => (
                    <td className="num" key={run.provider}>
                      <strong>
                        {run.passed}/{run.cases}
                      </strong>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            {redTeam
              .map((run) => `${PROVIDERS[run.provider] ?? run.provider}: ${run.model_exercised} respostas do modelo, ${run.model_fallbacks} fallbacks`)
              .join(" · ")}
            . Os demais ataques são barrados por políticas determinísticas antes do modelo. A primeira rodada (v1) teve
            um falso positivo do verificador, corrigido e mantido no repositório.{" "}
            Relatórios:{" "}
            {redTeam.map((run, index) => (
              <span key={run.report}>
                {index > 0 && " · "}
                <a href={REPO + "evaluations/results/" + run.report} target="_blank" rel="noreferrer">
                  {PROVIDERS[run.provider] ?? run.provider} <ExternalLink size={12} />
                </a>
              </span>
            ))}
          </p>
        </section>
      )}

      <section aria-labelledby="channels-title" className="panel" style={{ display: "grid", gap: 10 }}>
        <h2 id="channels-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Send size={18} aria-hidden="true" /> Também no Telegram
        </h2>
        <p className="muted">
          O mesmo agente responde no{" "}
          <a href={BOT} target="_blank" rel="noreferrer">
            @mesa_food_discovery_bot <ExternalLink size={12} />
          </a>
          , 24 horas por dia. Um gateway em Go valida o segredo do webhook, descarta duplicatas e enfileira a mensagem
          em um Redis Stream; o worker Python consulta o agente e responde. Como o servidor gratuito hiberna, o
          gateway acorda o worker ao enfileirar: a primeira resposta após um período parado leva até um minuto.
        </p>
        <p className="muted" style={{ fontSize: 12 }}>
          O WhatsApp usa o mesmo gateway, fila e worker, com assinatura HMAC; o fluxo foi aprovado de ponta a ponta
          com a API da Meta simulada.{" "}
          <a href={REPO + "docs/CHANNELS.md"} target="_blank" rel="noreferrer">
            Canais <ExternalLink size={12} />
          </a>
        </p>
      </section>

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
        <p>
          Contingência: 52/52 cenários com o provedor fora do ar continuam respondendo pelo glossário, com cada item
          conferido. Juízes LLM de relevância foram testados e reprovados na calibração; nenhuma nota deles aprova o
          produto.
        </p>
        <p>
          <a href={REPO + "docs/EVALUATION.md"} target="_blank" rel="noreferrer">
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
