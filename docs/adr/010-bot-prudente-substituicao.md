# ADR-010 — O substituto do desconectado é um bot prudente

- **Status:** Aceito
- **Contexto:** Fase 76 do `todo.md`
- **Decisores:** mantenedor

## Contexto

Com `substituir_desconectado_por_ia` ligada, quem cai no meio da partida deixa de
jogar: a IA assume os dados, o turno e a identidade (mesmo `client_id`/`chave_secreta`)
e a mesa segue. O problema é **quem** entra no lugar: o bot de hoje é sorteado por
nível com personalidade própria (`ia_risco`/`ia_agressividade` em `criar_ia` ou
`sorteiar_personalidade`), ou seja, o substituto de um humano que fechou a aba pode
abrir a aposta que acabou de ser fechada, com limiar de desconfiança baixo e
impulso aleatório por lance.

O jogo é casual, sem contas, sem ranking e sem aposta real — mas a mesa é social: o
que machuca é o resto da mesa **perceber** a falta de alguém e o tempo de jogo virar
uma sequência de apostas absurdas em nome de quem saiu. Pior, um "represente" que
arrisca faz o grupo desconfiar do sistema inteiro, e o sujeito pode nem ter sido ele
quem saiu (o bot fica com o nome dele).

Restrições reais: serverless (o estado vive no store distribuído), sem estado local
entre requests, sem estado global de sala, sem UI nova, sem i18n novo, motor de IA
puro (nunca lê `rodada.todos_os_dados`) e bots nunca viram master. A política do
arquétipo também tem que ser **verificável por conta própria** (`verificar.py`), não
só "parece prudente na partida".

## Decisão

O jogador substituído recebe o arquétipo **`ia.ESTILO_PRUDENTE`** (campo
`Jogador.ia_estilo`, persistido na partida — `versoes` 9→10). `ia.eh_prudente` desvia
`decidir` para `_decidir_prudente` **antes** de personalidade e nível:

1. **Desconfiar só com a conta clara:** só quando `P < _limiar_prudente(rodada)`
   (0,32 subindo 0,02 por lance, teto 0,45) — sem ruído, sem o impulso aleatório dos
   níveis.
2. **Apostar o que o próprio dado sustenta:** quantidade de dados `<=` suporte dos
   próprios dados (coringa vale como qualquer resultado, então a aposta é verdadeira
   aconteça o que acontecer com os outros), escolhida entre as cobertas de menor
   exposição; variação de 1 entre as duas menores para não ser robô de mesa.
3. **Sem coberta, a mínima jogada legal** (menor quantidade; coringa/face mais baixa
   no empate) — o mais perto de "só passar a vez" que o jogo permite, já que não
   existe passar.
4. **Abertura:** 1 dado, na face de maior suporte.
5. **O nível não decide a jogada:** `ia_nivel_padrao` da sala continua mandando no
   tempo de pensamento e no bônus de leitura dos níveis 3/4, nunca na aposta. A
   personalidade (`ia_risco`/`ia_agressividade`) é **inerte** no prudente.
6. **`retomar_identidade` limpa `ia_estilo`** junto de `ia_nivel`: quem volta joga
   como humano.
7. **O `🤖` vai no apelido guardado**, no mesmo campo do bot natural
   (`ia.marcar_substituto` / `ia.remover_marcador_ia`), e não num render do
   cliente: assim card de partida, fichas de confirmação, narração e lista da
   espera mostram a troca de uma vez, sem evento/chave nova. Como o apelido é a
   chave dos `id`s dos cards no cliente, a troca e a volta reconstroem a tela da
   sala inteira (`funcoes_gerais.reconstruir_tela_sala`, o mesmo caminho do
   snapshot de reconexão) — na troca **antes** de `ia.processar`, para o
   `atualizar_turno` do turno do substituto não procurar uma linha de dados num
   card que ainda tem o id do nome antigo. Apelido marcado que colida com outro
   jogador da sala fica sem marcador (dois ids iguais quebram o front).

Bots criados pelo master (`adicionar_ia`/`completar_com_ias`) continuam no
repertório por nível — a Fase 76 é sobre o **substituto**, não sobre o bot em geral.
Nenhum evento, chave i18n, select ou snapshot novo: o comportamento é invisível para
o cliente.

## Consequências

- Positivas: quem permanece na mesa sente a falta de alguém de forma branda e
  consistente, e ninguém ganha chamando a aposta do "desaparecido"; o estilo viaja
  no store, então **outra instância** reconstrói a sala e o prudente continua
  prudente; a política é auditável por `verificar.py` (grade de turnos, grade de
  coberta, anti-arrastão).
- Negativas / trade-offs aceitos: o prudente é **previsível** (pouca variadinha, é o
  que o torna auditável) e ganha menos pontos contra quem blefa; o limiar
  subindo por lance é o que impede a mesa de arrastar quando a rodada vira só de
  prudentes (`simular_ia --estilo prudente` fecha), mas é uma heurística de
  convergence, não uma garantia formal de terminação; a aposta mínima ainda é uma
  aposta (pode ser blefe), só que o menor possível.
- O que isso proíbe: reintroduzir ruído/impulso/personalidade no caminho prudente;
  usar `ia_estilo` como config de sala (é estado de jogo — muda no meio da partida
  e precisa migrar com o store); dar ao prudente botão/evento/UI próprio sem abrir
  novo ADR; fazer o `nível` escolher a aposta do prudente; trocar o apelido do
  jogador no meio da rodada sem reconstruir a tela da sala.
