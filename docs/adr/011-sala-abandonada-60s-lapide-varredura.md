# ADR-011 - Sala abandonada morre em 60s: carimbo próprio + lápide + varredura

- **Status:** Aceito
- **Contexto:** Fase 77 — salas vazias (só bots, ou ninguém) persistiam por 7 dias no store e reapareciam na busca
- **Decisores:** mantenedor

## Contexto

Uma sala é cancelada quando **nenhum humano está conectado**. Isso inclui o
`status` de espera: até a Fase 77, o `_gc_sala` só expurgava quem passava
da janela de graça, e a sala era removida no disconnect do último humano.

Três defeitos independentes conviviam:

1. **A janela de reconexão matava a partida cedo demais.** A graça é de 30s,
   mas o expurgo rodava a partir dela. Quem voltava em T+40s (um reload de
   celular, uma troca de rede) recebia `vaga_perdida_inatividade` em vez de
   retomar a sessão: a mesa sumia, e o placar com ela. O sintoma era raro e
   parecia "o jogo bugou", não uma política.
2. **Sala morta não morria.** Quando a sala ficava só com bots persistidos
   (instância serverless morta sem `disconnect`, Fase 29/H2), o `_gc_sala`
   existia mas só rodava quando alguém *tocava* a sala. Sem humano, ninguém
   tocava: a sala vivia até o TTL de 7 dias e continuava na busca como
   fantasma — o pior tipo de lixo, o que o usuário vê.
3. **"Sem humano" não tinha relógio próprio.** `visto_em` é atualizado por
   heartbeat e pelos fluxos de IA, e `desconectado_em` é por jogador, não por
   sala. Não dava para saber "quando foi o último humano" sem recomputar a sala
   inteira.

Forças em jogo:

- **serverless:** nada de timer no processo (ADR-001) — a limpeza tem de ser
  puxada por quem já está indo ao store;
- **cross-instance:** o cancelamento disputa com o `retomar_identidade` que está
  chegando; sem lock, a varredura apaga a sala enquanto a retomada a ressuscita
  (ADR-002);
- **casual:** o usuário fecha a aba; a partida não pode virar refém de um
  cliente que não existe mais;
- **custo:** varrer o índice inteiro a cada evento seria um martelo no store;
- **UX:** quem volta tarde precisa de uma resposta honesta, não de um erro
  genérico de "sessão de outra sala".

## Decisão

**Carimbo de ausência na sala (`Lobby.sem_humano_em`) + janela de 60s +
lápide one-shot + três caminhos de limpeza.**

**1. `sem_humano_em` é o relógio da sala.** É setado no `disconnect` (e em
`reavaliar_vida`, que todo caminho que muta estado chama) quando não há jogador
fora da graça nem espectador conectado — e **limpo assim que existe humano**.
Espectador conta como humano por decisão explícita: ele está usando o serviço
e assistindo; tratá-lo como ausência cancelaria a partida debaixo de quem
assiste. `visto_em` foi descartado para isto: ele também é tocado por IA e por
heartbeat, então não distingue "ninguém aqui" de "alguém aqui mas quieto".

**2. Três checagens em ordem, no `_gc_sala`.** Cancelamento vence tudo; depois,
sala sem humano **dentro** da janela não expurga ninguém (a graça de 30s só
substitui humano por bot quando há outro humano na mesa); com humano presente,
o expurgo roda como sempre. A ordem é o ponto: inverter as duas primeiras é o
bug da Fase 23.

**3. Três caminhos limpam, por camadas:**

| camada | gatilho | alcance |
| --- | --- | --- |
| `_gc_sala` | qualquer evento que toque a sala | imediato, barato |
| `listar_partidas` | quem está na home (já leu o índice) | oportunista, 30s por instância |
| `gc_salas.py` | serviço no `docker-compose` da VPS | garantido, 30s |

A barreira final é o **TTL curto**: `salvar_sala` passa 120s quando a sala está
sem humano (7 dias quando tem gente). Se os três caminhos falharem — cron
morto, ninguém na home, instância evaporada — o store ainda assim expira. O TTL
aplica-se também à chave de resumo, senão o id sobreviveria 7 dias no índice e
reapareceria na busca como fantasma.

O serviço da VPS é garantido; na Vercel não é (o cron lá é 1x/dia), e por isso
a varredura oportunista existe — é o único caminho que roda nos dois deploys, e
usar `forcar` no `gc_salas.py` deixa o ritmo de cada processo no seu próprio
ritmo.

**4. Lápide one-shot (`dadinho:lapide:<id>`, 300s).** O cancelamento é silencioso
no servidor — a sala está vazia, não há ninguém na room para `emit`. O único
afetado é quem volta depois, e ele precisa de um motivo verdadeiro: sem a
lápide, `vagas_recentes` já foi apagado junto com a sala e o `retomar_negado`
cairia no "sessão de outra sala", que é mentira. A lápide é consumida na
primeira leitura (por isso one-shot) e devolve `msg.partida_cancelada`.

**5. O retorno é realocado, não cuspido.** Com a sala cancelada, quem volta
recebe `connect_start` + snapshot da sala **zerada no mesmo código** e o
`retomar_negado` com o motivo. Sem realocar, o `connect_start` adiado
(`tem_chave=1`, Fase D2) ficaria sem snapshot e a tela travaria no watchdog —
um erro trocado por outro.

**6. O prazo é julgado em `retomar_identidade` também.** Confiar só no GC
permitiria ressuscitar uma sala vencida: a linha que limpa o carimbo na retomada
é justamente o que tornaria a checagem impossível, milissegundos depois. A
ordem correta é julgar, cancelar, realocar.

## Consequências

**Boas:**

- O bug do T+40s some: a mesa sobrevive à janela inteira, não só à graça.
- Lixo some em ~90s (60s de janela + 30s de cadência) em vez de 7 dias, e sem
  depender de alguém abrir aquela sala.
- O motivo do cancelamento é honesto e no idioma do usuário.
- Nenhuma instância precisa de estado em memória: o carimbo viaja no `Lobby`.

**Prejuízos:**

- **Quem chega no meio da janela entra na sala existente**, em vez de receber
  uma sala recriada do zero. Num código cuja partida está só com bots, ele vira
  espectador de uma mesa que ninguém está jogando (ou entra na espera, se a sala
  nem começou). É o comportamento coerente com "a sala está viva há menos de
  60s"; o custo é uma sala em `espera` abandonada que pode receber um visitante
  antes de morrer.
- **A varredura é O(índice)** — limitada a 50 resumos por passada, com o resto
  para a próxima. Como a sala cancelada sai do índice, a fila anda sozinha.
- **`gc_salas.py` é mais um serviço para operar.** Ele é opcional no sentido de
  que o TTL ainda cobre a ausência dele, mas perde-se a janela de 60s (vira 120s
  de TTL).
- O `Lobby` ganhou um campo: a migração v10→v11 preenche `None` (= "nunca
  esvaziou"), que é o estado neutro e não cancela nada por acidente no deploy.

## Alternativas descartadas

- **Só o TTL curto (sem carimbo nem lápide):** mais simples, mas o motivo do
  cancelamento some (viraria "sessão de outra sala") e a janela vira "120s sem
  ninguém", indecifável a partir do estado.
- **Só o `_gc_sala`:** não roda em sala sem ninguém tocá-la — que é exatamente o
  caso que se quer limpar.
- **Cron HTTP na API:** seria uma rota pública nova (auth, nginx, rate limit de
  borda) para um laço de 30s que o `gc_salas.py` faz sem abrir porta nenhuma.
- **Cron da Vercel:** 1x/dia não dá a janela de 60s; e o deploy da VPS é o que
  tem processo persistente.
- **Estender a graça de 30s para 60s:** não é a mesma coisa. A graça é por
  jogador e controla *substituição por IA*; a janela é por sala e controla *morte
  da sala*. Juntá-las faria a mesa esperar 60s rodando em bots antes de virar
  a favor de quem está presente, e a grace continua valendo 30s quando há outro
  humano.
- **Emitir `partida_cancelada` para a sala:** impossível — o cancelamento só
  acontece com a sala vazia, não há cliente na room. Por isso a lápide existe.

## Verificação

- `verificar.py` §4: migração v10→v11, round-trip e presença no resumo.
- `tests/test_integracao.py` (`testes_fase77`), 6 casos: volta dentro da janela
  preserva a partida; varredura cancela e limpa o índice; retorno após o
  cancelamento avisa e realoca; sala com humano nunca é cancelada (selo vencido
  incluído); rate-limit de 30s; TTL curto e sua restauração.
- Testes da Fase 15/23/30 que codificavam "fecha na hora" foram reescritos para
  o novo contrato (sobreviver à janela, morrer vencida).
