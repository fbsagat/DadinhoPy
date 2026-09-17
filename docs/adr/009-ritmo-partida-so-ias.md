# ADR-009 — Ritmo da partida só de IAs: relógio no lobby + poll do espectador

- **Status:** Aceito
- **Contexto:** Fase 69 do `todo.md` (bug de mobile: partida só de IAs impossível de acompanhar)
- **Decisores:** mantenedor

## Contexto

Quando o último humano com dados é eliminado, a partida vira uma mesa só de
bots. Como o motor de IA roda **dentro do request** (ADR-001/005) e não há
timers no servidor, `ia.processar` simulava a partida inteira numa única
chamada: com 4 bots e 3 dados, uma só request emitia ~434 eventos e 48
narrações — tudo entregue ao cliente num burst.

O cliente tinha uma defesa parcial: a fila serial de eventos
(`MAX_ATRASO_FILA`, Fase 53) colapsava as pausas de "pensamento" acima de 4s.
Resultado: quem assistia via a partida inteira passar em ~4s, sem chance de
acompanhar. No mobile o freeze do DOM com centenas de callbacks piorava.

Forças em jogo:
- **serverless:** nada de `sleep`/thread/timer de fundo (ADR-001);
- **cross-instance:** o ritmo tem de valer entre réplicas (ADR-002);
- **casual:** quem assiste pode fechar a aba a qualquer momento — a sala não
  pode ficar presa esperando um cliente que não existe mais;
- **custo:** o poll é barato e espaçado; não pode virar um martelo no store.

## Decisão

**Relógio no Lobby (`proximo_lance_em`) + poll do espectador
(`espectador_leitura`).** `ia.processar` ganha dois modos:

- **modo legado (inalterado):** há humano com dados, ou não há espectador
  humano. O laço simula até acabar — como sempre.
- **modo assistido:** não resta humano com dados (eliminado ou só bots) **e**
  há humano na sala fora da mesa (espectador). O laço libera **um lance** por
  chamada (uma rolagem, um turno, uma conferência ou o fecho da vitória).

O ritmo vive no estado persistido, não no processo:

1. `Rodada.proximo_lance_em` (páginas 1/2) e `Partida.proximo_lance_em`
   (páginas 3/4) guardam o instante do próximo lance. `ia._gravar_relogio`
   escreve nas duas, então a leitura é consistente em qualquer página. O campo
   é serializado (`VERSAO_ATUAL` 8 → 9) e vale para todas as instâncias.
2. O intervalo de um lance é o "tempo de pensamento" dos bots
   (`narrador.tempo_pensamento(..., so_ias=True)`), limitado por
   `INTERVALO_LANCE_MIN_MS`/`INTERVALO_LANCE_MAX_MS` (evita rajada por um lado e
   travamento por outro).
3. O **espectador paga o ritmo**: em `static/script.js`, ao receber uma
   `narracao` de IA ele agenda `espectador_leitura`; o handler roda
   `ia.processar` sob o lock e responde `espectador_ritmo` com `restante_ms`.
   O cliente reagenda o poll com esse tempo — nunca o "adivinha".
4. O **heartbeat** entra como rede de segurança: quando a sala está em partida
   só de IAs com relógio armado, força o caminho lockado mesmo com o cache
   quente, cobrindo o caso de o polling do espectador morrer.
5. Sem espectador, `ia.processar` volta ao modo legado — a sala nunca fica presa
   com ninguém olhando (o mesmo vale para uma partida pura de bots).

**Rejeitadas:**
- **Replay no cliente** (manter a simulação completa e só não colapsar a fila):
  o servidor já teria finalizado a partida e resetado o lobby, enquanto o
  cliente ainda "assistia" um passado — inconsistente em refresh, e reintroduz o
  lag acumulado que a Fase 53 resolveu.
- **Aumentar `MAX_ATRASO_FILA`:** paliativo; ritmo é propriedade do servidor.
- **Sleep/timer no servidor:** viola a invariante serverless (ADR-001).

## Consequências

- Positivas: o espectador acompanha a partida de IAs no ritmo real de uma
  partida; o estado autoritativo avança um lance por vez.
- Positivas: cross-instance de graça — o relógio vive no blob; o lock
  distribuído garante que dois polls simultâneos não movam o turno duas vezes
  (o segundo lê o relógio já avançado e só responde o `restante_ms`).
- Negativas/trade-off: o avanço da partida assistida depende de um cliente
  vivo. Mitigado pelo modo legado (sem espectador, simula) e pelo heartbeat
  como segunda fonte.
- Negativas: mais um campo de estado a serializar/migrar e um evento novo
  (`espectador_leitura` → `espectador_ritmo`), com o teste de integração
  `espectador-ritmo-so-ias` guardando as propriedades.
- Proíbe: pôr `sleep`/`threading.Timer` no caminho do ritmo; guardar
  `proximo_lance_em` em variável de módulo (quebraria entre instâncias); fazer o
  cliente arredondar o ritmo sozinho (o servidor é a fonte).
