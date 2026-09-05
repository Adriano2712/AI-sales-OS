# SDR Assistido / Message Generation

**Status: built (Fase 8).**

```
Opportunity -> (humano escolhe canal e clica "Gerar mensagem") -> MESSAGE_GENERATION job
  -> AI Writer (Sonnet) -> Message (DRAFT)
  -> humano edita/aprova/rejeita
  -> envio manual (fora do sistema)
  -> humano marca SENT
```

## Diferente de todo o resto do pipeline: geração é acionada pelo humano

Discovery → Enrichment → Website Analysis → Business Analysis → Scoring
rodam automaticamente, encadeados. Message Generation não — é a única etapa
que gasta dinheiro real (Sonnet, mesmo custo da Fase 5) sem que exista uma
necessidade determinística de rodar (nem toda oportunidade LOW merece uma
mensagem). Só roda quando um humano escolhe uma oportunidade específica e um
canal e clica em gerar (spec seção 39).

## Sem entidade `Contact`

Discovery nunca coletou o nome de uma pessoa específica — só telefone/site
da empresa (dado público de negócio, spec seção 65, não dado pessoal). A
mensagem referencia `Opportunity`/`Company` direto; canal e destino são o
que a empresa já tem cadastrado, escolhido pelo humano na hora de enviar —
nada inventado.

## `do_not_contact` (spec seção 50)

Campo booleano em `Company` (não uma tabela separada — mesma razão do item
acima: não existe uma entidade de contato pessoal pra vincular). Checado em
dois pontos, não só um:

1. **Na geração** (`POST /opportunities/{id}/messages` e dentro do próprio
   job) — nunca gera um rascunho para uma empresa marcada.
2. **No envio** (`PATCH /messages/{id}` para `SENT`) — mesmo que a mensagem
   já tivesse sido aprovada *antes* de a empresa ser marcada, o sistema
   ainda assim bloqueia o envio na hora.

## Idempotência (spec seção 54 / 39)

Uma mensagem `DRAFT` ou `APPROVED` já existente para o mesmo
`(opportunity, channel)` é reaproveitada — clicar "gerar" duas vezes não
gasta duas chamadas de IA. Regenerar depois de `REJECTED`/`SENT` cria uma
nova linha (canal/oportunidade permitem múltiplas mensagens ao longo do
tempo, diferente de `Opportunity`'s unique constraint).

## Editável antes de aprovar

`PATCH /messages/{id}` aceita `text` — só quando `status=DRAFT`. Depois de
`APPROVED`, o texto trava (é o que foi aprovado pra envio, não faz sentido
mudar por baixo). Editar não é gerar de novo — zero custo de IA.

## Máquina de estados

```
DRAFT -> APPROVED -> SENT
DRAFT -> REJECTED
APPROVED -> REJECTED
```
`SENT`/`REJECTED` são terminais. Validado por `validate_message_status_transition`
(função pura, testada isoladamente — mesmo padrão de `campaigns/service.py`).

## AI Writer

Sonnet (`docs/AI.md` já listava "message generation" como tarefa
reasoning-heavy desde a Fase 0). Input: nome/segmento/cidade da empresa,
`problem`/`potential_solution`/`reasons` da Opportunity — nada além disso.
Regra do prompt, direto da spec seção 48: nunca inventar cliente, resultado,
funcionalidade ou informação pessoal; se a evidência for fraca, manter a
mensagem genérica e honesta em vez de parecer mais informado do que é.

**Real finding**: sem uma identidade real de remetente, o modelo improvisava
sozinho uma linha tipo "somos uma software house **daqui de Salvador**" /
"**daqui de Natal**" — inventando presença local que não existe (violação
silenciosa da regra de nunca inventar, só percebida ao ler mensagens reais
já geradas). Corrigido com `SENDER_COMPANY_NAME`/`SENDER_COMPANY_LOCATION`
(opcionais — sem eles, a mensagem fica genérica, "uma software house", sem
inventar local nenhum) passados como fato fixo pro prompt, que agora proíbe
explicitamente afirmar presença local no lugar do prospect. Trabalho remoto
é normal nesse setor — o prompt instrui a nunca pedir desculpa pela
distância nem escondê-la.

## Sem envio automático (spec seção 47/49)

Nenhuma integração real com WhatsApp/email/LinkedIn. "Marcar como enviada"
é só um campo no banco — o humano copia o texto e manda pelo canal que
quiser, fora do sistema. `response` é texto livre que o humano loga
manualmente se receber uma resposta; o sistema não busca nem inventa isso.

## Rascunho no Gmail (canal EMAIL, post-Fase-8) — ainda não é envio

`POST /api/v1/messages/{id}/gmail-draft` (só pra mensagens `EMAIL`
`APPROVED`) cria um rascunho de verdade na pasta de Rascunhos do Gmail
configurado (`notifications/gmail_draft.py`, via IMAP) — endereçado ao
`Company.email` (ver abaixo), com o texto já aprovado. **Não envia nada** —
o rascunho fica lá esperando o humano revisar e mandar, mesma filosofia do
resto da Fase 8. Usa a mesma Senha de App do Gmail já configurada pro
digest diário (`GMAIL_SMTP_USER`/`GMAIL_SMTP_APP_PASSWORD`), sem credencial
nova. A pasta de rascunhos é descoberta via a flag IMAP `\Drafts`
(RFC 6154), nunca fixada como `[Gmail]/Drafts` — o nome muda com o idioma
da conta (confirmado numa validação real: a conta usada aqui é
`[Gmail]/Rascunhos`, não a versão em inglês).

### `Company.email` — de onde vem

Nunca coletado na descoberta (nenhum provider expõe isso). Preenchido por
`website_analysis/service.py` a partir do primeiro link `mailto:` real
encontrado ao crawlear o próprio site da empresa — mesma regra de nunca
sobrescrever um valor já conhecido que `merge_missing_fields` já aplica a
telefone/site. Sem site, ou sem `mailto:` no site, fica `None` — o botão de
rascunho simplesmente não aparece nesse caso.

## Fora de escopo

Feedback loop (spec seção 61 — "primeiro coletar dados", ainda não existe
mensagem real enviada pra ter feedback sobre); Conversation Engine (spec
seção 51, fase futura); qualquer integração real de envio.

## Real finding

Gerada uma mensagem real (Sonnet) para uma oportunidade real do dev tenant
— CAPS III "Viver em Liberdade" (Regional Leste), um serviço público de
saúde mental descoberto na campanha de teste de clínicas em Sorocaba. O
texto gerado reconheceu sozinho, sem ser instruído especificamente sobre
isso, que "por ser um serviço público" o processo de contratação pode
diferir de uma empresa privada e perguntou se passaria por licitação —
inferência razoável a partir do nome da empresa, não uma invenção (a
diferença exigida pela seção 48 é sutil e o modelo respeitou).

## Achado operacional (não é bug de produto)

Descoberto durante a validação real desta fase: matar um processo de
worker/API em segundo plano nesta configuração Windows (via `TaskStop` do
harness) às vezes só encerra o processo-lançador do venv (`Scripts/python.exe`),
deixando o interpretador real (`C:\Python312\python.exe`) órfão — ainda
vivo, ainda conectado ao Redis/Postgres, ainda rodando o código *antigo* em
memória. Isso produziu um falso negativo real durante a validação desta
fase (um erro de atributo em `Company.do_not_contact` que na verdade já
tinha sido corrigido, mas o processo órfão não sabia disso). Fix usado:
verificar `Get-CimInstance Win32_Process` por `python.exe` e matar por PID
real antes de assumir que um restart limpou o estado.
