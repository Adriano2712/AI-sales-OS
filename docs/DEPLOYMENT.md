# Rodando sozinho todo dia (Fase 18, Step 8)

Objetivo do usuário: o sistema roda sozinho, todo dia, sem precisar abrir
terminal nenhum. Só dois processos locais precisam ficar de pé o tempo
todo para isso — `workers/run.py` (processa os jobs) e
`workers/scheduler.py` (dispara a rotação diária de 8 países, manda os
emails de resumo, reenfileira jobs presos). A API e o frontend web são
**opcionais** para esse fluxo — nada na automação diária passa por eles;
eles só importam se alguém for usar o painel.

Redis (Upstash) e Postgres (Supabase) já são hospedados na nuvem — não
precisa rodar nada disso localmente.

## Os scripts (`workers/scripts/`)

- `run_worker_daemon.ps1` — mantém `workers/run.py` rodando: se o
  processo cair por qualquer razão (um job trava tudo, já que o
  `SimpleWorker` do Windows roda em-processo — ver `workers/run.py`),
  reinicia sozinho em 10s.
- `run_scheduler_daemon.ps1` — mesma coisa para `workers/scheduler.py`.
- `_load_dotenv.ps1` — carregado pelos dois acima. Necessário porque
  `MIGRATIONS_DATABASE_URL` (usado pelo novo `_real_tenant_ids` do
  scheduler, ver Fase 18) é lido direto de `os.environ`, não pelo
  `Settings` do pydantic — que lê o `.env` internamente mas nunca exporta
  pra fora. Um humano rodando na mão sempre deu `source .env` antes; um
  processo iniciado sem terminal nenhum não tem isso, então o daemon
  carrega o `.env` ele mesmo antes de chamar o Python.

Logs vão para `workers/logs/worker.log` e `workers/logs/scheduler.log`
(git-ignorados, UTF-8, `python -u` pra não bufferizar).

## Registrar como Tarefa Agendada do Windows — passo manual

**Isso não pôde ser feito automaticamente**: o ambiente onde essa sessão
roda não tem permissão pra criar Tarefas Agendadas no Windows (tanto
`Register-ScheduledTask` quanto `schtasks.exe` retornaram "Acesso negado"
mesmo pra uma tarefa trivial de teste — não é um problema de sintaxe, é
uma restrição real do ambiente). Rode isto **uma vez**, num PowerShell
normal (não precisa ser administrador):

```powershell
$repoRoot = "C:\Users\Samsung\Downloads\AI Sales OS"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$trigger = New-ScheduledTaskTrigger -AtLogOn

$workerAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\workers\scripts\run_worker_daemon.ps1`""
Register-ScheduledTask -TaskName "AISalesOS-Worker" -Action $workerAction -Trigger $trigger -Settings $settings -Description "AI Sales OS: RQ job worker (workers/run.py), auto-restart loop" -Force

$schedulerAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\workers\scripts\run_scheduler_daemon.ps1`""
Register-ScheduledTask -TaskName "AISalesOS-Scheduler" -Action $schedulerAction -Trigger $trigger -Settings $settings -Description "AI Sales OS: daily scheduler (workers/scheduler.py) - 8-country rotation, digest emails, retries" -Force
```

Isso registra as duas tarefas pra iniciar sozinhas **todo login no
Windows** (`-AtLogOn`), sem limite de tempo de execução (o padrão do
Windows mata tarefas depois de 3 dias — desligado aqui de propósito, já
que cada uma roda pra sempre em loop), e reinicia até 5x se cair.

Depois de registrar, pra já começar a rodar agora (sem esperar o próximo
login):

```powershell
Start-ScheduledTask -TaskName "AISalesOS-Worker"
Start-ScheduledTask -TaskName "AISalesOS-Scheduler"
```

## Verificar que está rodando

```powershell
Get-ScheduledTask -TaskName "AISalesOS-*" | Select-Object TaskName, State
Get-Content "C:\Users\Samsung\Downloads\AI Sales OS\workers\logs\scheduler.log" -Tail 20
Get-Content "C:\Users\Samsung\Downloads\AI Sales OS\workers\logs\worker.log" -Tail 20
```

## Parar

```powershell
Stop-ScheduledTask -TaskName "AISalesOS-Worker"
Stop-ScheduledTask -TaskName "AISalesOS-Scheduler"
```

Isso mata o PowerShell da tarefa, mas o loop interno do daemon já religou
o Python várias vezes durante os testes — se `Stop-ScheduledTask` não
matar o processo `python.exe` junto, mate-o direto (`Stop-Process -Name
python -Force`) ou desregistre a tarefa (`Unregister-ScheduledTask -TaskName
"AISalesOS-Worker" -Confirm:$false`).

## O que acontece sem essa etapa manual

Nada quebra — os dois processos já estão rodando agora (iniciados
manualmente nesta sessão) e vão continuar até a máquina reiniciar ou
alguém fechar o PowerShell deles. A única coisa que falta é a
persistência **através de reinícios/logins** — por isso essa etapa deve
ser feita para o "roda sozinho todo dia" valer mesmo depois de reiniciar
o Windows.
