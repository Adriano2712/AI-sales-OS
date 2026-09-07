# Descoberta Diária + Resumo por Email

**Status: built. Descoberta autônoma configurável por campanha adicionada
(master-plan Fase 9). Relatório diário de oportunidades enriquecido +
contadores de resumo (master-plan Fase 10).** Um 4º processo local,
opcional — só faz algo quando você o deixa rodando (`workers/scheduler.py`),
junto com API + worker.

```
workers/scheduler.py (tick a cada 15min)
  -> hoje já rodou? (por segmento, rotaciona restaurants/clinics/b2b_services)
  -> não: cria/reusa campanha "Descoberta Diária (auto)" + dispara DISCOVERY
  -> tem digest pendente (run COMPLETED há mais de 30min, ainda não enviado)?
  -> sim: manda DOIS emails independentes, cada um com seu próprio controle
     de idempotência no audit_log (falha/atraso de um não afeta o outro):
     1. resumo de negócio (nome/telefone/site/score/classificação)
     2. diagnóstico de sites (score digital + problemas concretos + parágrafo
        de impacto gerado por IA) — ver docs/WEBSITE_ANALYSIS.md
```

## Por que um processo separado, não dentro do worker

`workers/run.py` fica bloqueado dentro de `worker.work()` — não sobra
espaço pra também rodar um loop de agendamento. Um processo dedicado,
simples (`while True: tick(); sleep(900)`), evita mexer no worker existente.

## Busca "Brasil inteiro" — só o Apify participa

`NATIONWIDE_CITY_SENTINEL = "BRASIL"` (`discovery/base.py`). Quando uma
campanha usa esse valor como cidade:

- **Overpass rejeita de propósito** (`DiscoveryProviderError` — ver
  `providers/overpass.py`) — uma query de país inteiro contra a instância
  pública gratuita seria sobrecarga real, ela já dá rate-limit com 3
  cidades seguidas. O fallback existente (um provider falhar não derruba
  o outro) cuida disso sem nenhuma mudança no job handler.
- **Apify aceita nativamente** — a documentação do próprio actor diz pra
  passar só o país que ele mesmo divide em sub-regiões.
- **A cidade real de cada empresa vem do próprio resultado do Apify**
  (`item["city"]`), não da campanha — senão toda empresa apareceria como
  cidade "BRASIL". Validado de verdade: uma campanha nacional real trouxe
  5 empresas em Boa Vista/RR, geograficamente bem longe de qualquer cidade
  testada antes.

## Rastreamento: qual empresa veio de qual run

`Company.campaign_run_id` (migration 0010) — setado só na criação, nunca
num merge posterior (spec: uma re-descoberta não deve fazer a empresa
"reaparecer" no resumo de outro dia). É isso que permite ao digest saber
exatamente quais empresas um run específico introduziu.

## Email — Gmail SMTP, sem serviço pago

`notifications/email_sender.py` usa `smtplib` da biblioteca padrão do
Python, direto pro Gmail (`smtp.gmail.com:587`, STARTTLS). Precisa de uma
**Senha de app** do Google (16 caracteres, gerada em
`myaccount.google.com/apppasswords`, exige verificação em duas etapas) —
nunca a senha real da conta.

Conteúdo do email: nome, cidade/estado, telefone, site, score de negócio e
classificação — só dado real já coletado, nunca inventado (empresa ainda
sem análise aparece como "ainda em análise", não como zero ou vazio).

## Configuração (todas opcionais — sem elas, o recurso correspondente só não roda)

```env
GMAIL_SMTP_USER=...
GMAIL_SMTP_APP_PASSWORD=...
DAILY_DIGEST_RECIPIENT_EMAIL=...
DAILY_DISCOVERY_TENANT_ID=...   # sem isso, o scheduler não faz nada
```

## Quantidade e custo (decisão explícita do usuário)

5 empresas/dia, segmento rotativo. Custo real medido numa campanha real de
teste: Apify (5 resultados, fração do crédito grátis mensal) + Anthropic
(5 análises de negócio reais, ~$0,01-0,013 cada) — **~$0,05-0,07/dia**, ou
seja, **~$1,50-2,00/mês** rodando todo santo dia. Ajustável em
`workers/scheduler.py:_DAILY_TARGET_QUANTITY`.

O parágrafo de impacto do diagnóstico de sites (`ai_diagnostic.py`) soma
uma segunda chamada de IA por empresa com site — mesma ordem de grandeza
(~$0,01/empresa), só quando o site carregou (pulada em sites fora do ar,
ver docs/WEBSITE_ANALYSIS.md). Com 5/dia isso é centavos a mais por mês.

## Real finding: fila de teste suja a fila de produção

Descoberto durante a validação real desta feature: os testes de
integração que exercitam `discovery.py`'s `_run()` diretamente **também
enfileiram jobs encadeados reais** (`WEBSITE_ANALYSIS`/`BUSINESS_ANALYSIS`)
no Redis real do projeto — não só mockam o provider, o `get_queue()`
dentro do handler é sempre real. Como os testes limpam o tenant no banco
mas nunca limpam o que já foi pro Redis, isso deixa um acúmulo real de
jobs órfãos (referenciando tenants já deletados) que só aparecem quando um
worker de verdade sobe e tenta processá-los — degradam graciosamente
(log + skip), mas atrasam qualquer trabalho real enfileirado depois deles
(foi exatamente isso que atrasou a validação real desta feature: 23 jobs
órfãos na frente do nosso). Não corrigido nesta sessão (fora do escopo
desta tarefa) — ver seção "Problemas" do relatório.

## Stateless — seguro reiniciar o processo a qualquer momento

Nada de estado em memória entre ticks: "já rodou hoje?" e "digest já
enviado?" são sempre re-derivados do banco (`CampaignRun.started_at`) e do
`audit_log` (`daily_digest_sent`). Matar e religar o processo no meio do
dia nunca duplica um disparo nem perde o controle do que já foi feito.

## Retry de jobs presos (post-Fase-9, todo tenant, independente do digest)

Achado real durante a validação da Fase 9 (aconteceu duas vezes, com
empresas reais): quando um handler de job (`business_analysis.py`,
`website_analysis.py`, etc.) captura um erro da IA e marca o job
`RETRYING`, ele nunca deixa a exceção subir pro RQ — então a fila sempre
acha que o job "terminou com sucesso" (é por isso que o log mostra
"Successfully completed" mesmo quando a análise falhou por dentro), e o
retry nativo do RQ nunca dispara. Sem esse `scheduler.py`, um job marcado
`RETRYING` ficava preso pra sempre até alguém notar e reprocessar na mão.

Agora, a cada tick, o `scheduler.py` varre jobs `RETRYING` de **todos os
tenants** (não só o `DAILY_DISCOVERY_TENANT_ID`) e reenfileira, até um
limite de 3 tentativas (`Job.attempts`, já existia) — depois disso vira
`FAILED` de verdade, nunca fica em limbo silencioso. Isso roda mesmo que a
automação de descoberta diária esteja desligada — é uma questão de
confiabilidade geral do pipeline, não uma feature do digest. Validado de
verdade contra o banco real (job sintético RETRYING → reenfileirado
corretamente; job no limite de tentativas → virou FAILED corretamente).

## Master-plan Fase 9: descoberta autônoma configurável, por campanha

Antes desta fase, autonomia era tudo-ou-nada: **um único tenant**
(`DAILY_DISCOVERY_TENANT_ID`), **um único segmento por dia** (rotação fixa
de 3), sempre `cities=[NATIONWIDE_CITY_SENTINEL]` (Brasil inteiro),
`target_quantity` sempre 5 — nenhum outro tenant do sistema tinha qualquer
forma de rodar descoberta sem um humano clicar manualmente em "iniciar
run" a cada vez.

Agora **qualquer campanha, de qualquer tenant** pode optar por rodar
sozinha todo dia, com `Campaign.auto_discovery_enabled=True` — usando o
segmento/cidades/estado/país/quantidade/serviços/pesos **reais e já
configurados** dessa campanha específica, não os valores fixos do piloto
original. O piloto original continua funcionando exatamente como antes
(`_tick`, `_get_or_create_daily_campaign`, rotação de segmento,
`DAILY_DISCOVERY_TENANT_ID`) — nada nele foi tocado; a nova varredura
genérica (`_trigger_autonomous_campaign_runs_all_tenants`) roda **ao lado**
dele, nunca sobre a mesma campanha (o piloto nunca marca
`auto_discovery_enabled=True` na sua própria campanha sintética), então não
há risco de disparo duplicado.

**Mecanismo**: mesmo desenho de "varrer todos os tenants, isolar falha por
item" já provado em `_retry_stuck_jobs_all_tenants` — para cada tenant,
busca campanhas `ACTIVE` com `auto_discovery_enabled=True` e chama
`_ensure_todays_run` (já genérica, recebe `campaign` como parâmetro, zero
mudança necessária ali) para cada uma. Uma campanha falhando não impede as
outras.

**Limite de segurança de custo, aplicado em código**: a própria regra do
prompt mestre ("comece pequeno: 3, depois 10, nunca lote grande de uma só
vez") virou uma checagem real —
`campaigns/service.py::_MAX_AUTONOMOUS_TARGET_QUANTITY = 10`. Uma campanha
só pode ter `auto_discovery_enabled=True` com `target_quantity <= 10`
(checado tanto na criação quanto num PATCH parcial, contra o estado final
resolvido — não dá pra contornar setando os dois campos em requisições
separadas). Uma campanha manual (sem autonomia) não tem esse limite — quem
roda manualmente já está re-aprovando cada execução.

**Validação real end-to-end**, com um tenant descartável dedicado (nunca o
tenant real de desenvolvimento — ver o incidente de dados da Fase 8): (1)
campanha com `auto_discovery_enabled=True` disparou corretamente na
primeira varredura (1 `CampaignRun` criado, 1 job `DISCOVERY` enfileirado);
(2) segunda varredura no mesmo dia não duplicou (ainda 1 chamada de fila,
reaproveitando `_ensure_todays_run` sem nenhuma mudança); (3) tentativa de
criar campanha autônoma com `target_quantity=11` corretamente rejeitada
pelo limite de segurança. Tenant descartável limpo ao final (delete em
cascata via FK, nunca um `DELETE` genérico por `tenant_id`).

## Master-plan Fase 10: Relatório Diário de Oportunidades enriquecido

**Achado real durante a auditoria desta fase (não por um teste): o digest
nunca era enviado para as campanhas autônomas da Fase 9.**
`_maybe_send_pending_digests` filtrava só `Campaign.name.like("Descoberta
Diária (auto)%")` — o nome sintético que só `_get_or_create_daily_campaign`
(o piloto) cria. Uma campanha real de qualquer tenant com
`auto_discovery_enabled=True` (Fase 9) nunca batia nesse filtro — o
`DISCOVERY` disparava normalmente, mas o tenant nunca recebia email
nenhum sobre o resultado. Corrigido: o filtro agora aceita `OR
Campaign.auto_discovery_enabled.is_(True)`, e uma nova varredura
tenant-agnóstica (`_send_pending_digests_all_tenants`, mesmo desenho de
"varrer todo tenant, isolar falha por item" já usado no retry sweep e na
varredura de descoberta autônoma) roda a cada tick — não só para o tenant
piloto. `_tick` continua chamando `_maybe_send_pending_digests`
diretamente também (intocado, redundante mas inofensivo pro tenant
piloto — a checagem de idempotência via `audit_log` evita reenvio).

**Campos ricos por lead** (`DigestCompanyEntry`, `notifications/digest.py`)
— tudo já estava carregado em memória em `_send_digest_for_run`, nenhuma
query nova: `opportunity_score`/`confidence` (Fase 7), `service_fit_score`
(Fase 6), `buying_potential_summary` (Fase 6, linguagem de sinal já
validada na origem), `google_rating`/`google_review_count`/`instagram_url`
(Fase 4), `reasons` (motivos da oportunidade). Todos opcionais — uma
empresa cuja análise ainda não chegou naquele estágio simplesmente não
mostra a linha, nunca um valor inventado.

**Contadores de resumo** (`DigestSummary`, `build_digest_summary` — função
pura, testada isoladamente): total de oportunidades, quebra por
classificação (HIGH/GOOD/REVIEW/LOW), quantas ainda sem classificação
("ainda em análise", nunca somadas como LOW), e score médio de
oportunidade (calculado só sobre quem já tem score real). Aparece como uma
linha "Resumo:" no topo do email, antes da lista de empresas.

**Diagnóstico de sites também ficou mais honesto**: `SiteDiagnosticEntry`
ganhou `website_status` (Fase 5) — quando não há `digital_score`, o email
agora diz *por quê* (bloqueio automático, timeout, domínio não encontrado,
etc.) em vez de um genérico "ainda em análise" que confundia falha real
com análise pendente. Mantém a regra absoluta da Fase 5 explicitamente na
própria redação do email: um bloqueio anti-bot nunca soa como "site ruim".

**Compatibilidade**: `build_digest_subject/text/html` mantêm as mesmas
assinaturas — `summary` é um parâmetro novo e opcional (`None` por
padrão), então qualquer chamador antigo continua funcionando sem
alteração. `DigestCompanyEntry`/`SiteDiagnosticEntry` só ganharam campos
com valores padrão — nenhum teste ou fixture existente precisou mudar.

**Validação real end-to-end**, tenant descartável dedicado (nunca o tenant
real — ver o incidente da Fase 8): duas empresas reais, uma com dados ricos
completos (rating do Google, Instagram, `buying_potential_summary`,
motivos) e outra com o site bloqueado por anti-bot. O email de negócio
mostrou corretamente "Resumo: 2 oportunidade(s) (1 HIGH, 1 ainda em
análise) — score médio de oportunidade: 82.3" e todos os campos ricos da
primeira empresa; o email de sites mostrou "bloqueio automático detectado —
não foi possível confirmar o conteúdo real" para a segunda, nunca "site
ruim" nem "ainda em análise" genérico. Tenant descartável limpo ao final via
cascade de FK.

## Limitação conhecida (aceita, não corrigida — escopo de piloto)

Se o processo cair exatamente entre criar o `CampaignRun` e enfileirar o
job `DISCOVERY`, aquele dia fica com um run "fantasma" (existe, nunca
processa) e o scheduler não tenta de novo no mesmo dia (já viu um run com
`started_at` de hoje). Falha rara, não instrumentada — aceitável para uma
feature de teste/piloto, revisitar se isso virar produção real.
