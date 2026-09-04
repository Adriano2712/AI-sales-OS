# Descoberta Diária + Resumo por Email

**Status: built.** Um 4º processo local, opcional — só faz algo quando você
o deixa rodando (`workers/scheduler.py`), junto com API + worker.

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

## Limitação conhecida (aceita, não corrigida — escopo de piloto)

Se o processo cair exatamente entre criar o `CampaignRun` e enfileirar o
job `DISCOVERY`, aquele dia fica com um run "fantasma" (existe, nunca
processa) e o scheduler não tenta de novo no mesmo dia (já viu um run com
`started_at` de hoje). Falha rara, não instrumentada — aceitável para uma
feature de teste/piloto, revisitar se isso virar produção real.
