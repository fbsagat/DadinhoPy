"""Testes de integração do Dadinho (Fase 45, M5) — movidos de verificar.py.

Importado LAZY pelo runner DEPOIS de `_preparar_integracao()` setar os
globals em `tests.base` — o `from tests.base import *` abaixo captura os
valores já prontos.
"""
from tests.base import *  # noqa: F401,F403


def teste_b3_aposta_invalida():
    _limpar()
    clis, lobby = _conectar_trio(1)
    rodada = lobby.partidas[-1].rodadas[-1]
    vez = rodada.vez_atual
    cli_vez, chave_vez = clis[vez.username]
    invalidas = [
        {"dado": 0, "quantidade": 1},
        {"dado": 7, "quantidade": 1},
        {"dado": 3, "quantidade": 0},
        {"dado": 3, "quantidade": -1},
        {"quantidade": 2},
        {"dado": "abc", "quantidade": 2},
    ]
    for aposta in invalidas:
        cli_vez.emit("apostar", {"dados": {"chave": chave_vez, **aposta}})
    eventos = cli_vez.get_received()
    invalida = _achar_evento(eventos, "jogada_invalida")
    assert invalida is not None, "deve receber jogada_invalida"
    assert isinstance(invalida, dict) and invalida.get("txtchave"), \
        "jogada_invalida deve trazer a chave i18n (txtchave)"
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 0, "aposta inválida não pode criar turno"
    assert rodada.vez_atual == vez, "jogador da vez não pode mudar com aposta inválida"
    _desconectar_todos(clis)
    _limpar()
    _ok("B3 (aposta inválida)")


def teste_b6_bools_reais():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"com_coringa": "false", "publica": "false"}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.config["com_coringa"] is True, "string não pode desativar o coringa (B6)"
    assert lobby.config["publica"] is True, "string não pode tornar a sala privada (B6)"
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"com_coringa": False, "publica": False}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.config["com_coringa"] is False and lobby.config["publica"] is False
    c1.disconnect()
    _limpar()
    _ok("B6 (bools reais)")


def teste_b1_b7_desconexao_conferencia():
    _limpar()
    clis, _ = _conectar_trio(2)
    lobby = _rodada_ate_conferencia(clis)
    rodada = lobby.partidas[-1].rodadas[-1]
    perdedor_nome = rodada.perdedor.username if rodada.perdedor else None

    # B1: um jogador (que não o perdedor da rodada) confirma e cai; a
    # conferência não pode travar num fantasma.
    quem_cai = next(nome for nome in ("Ana", "Bia", "Caio") if nome != perdedor_nome)
    clis[quem_cai][0].emit("conferencia_final", {"chave": clis[quem_cai][1]})
    clis[quem_cai][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert lobby.pagina == 3, "desconexão na conferência não pode voltar para a página 2"
    assert rodada.conferiram == 0, "confirmação do desconectado deve ser desfeita (B1)"
    assert len(rodada.jogadores) == 2, "desconectado não pode continuar na rodada"
    assert len(lobby.jogadores) == 2

    for c, chave in clis.values():
        if c.is_connected():
            c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1, f"rodada 2 deve começar, página={lobby.pagina}"
    partida = lobby.partidas[-1]
    assert len(partida.rodadas) == 2, "deve ter criado a rodada 2"
    assert 1 in [j.dados_qtd for j in partida.jogadores], "alguém deve ter perdido um dado"

    for c, chave in clis.values():
        if c.is_connected():
            c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        if c.is_connected():
            c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2

    # B7: tab novo na página 2 da rodada 2 recebe reset_rodada com dados por jogador.
    c4, _, eventos_iniciais = _conectar()
    reset = _achar_evento(eventos_iniciais, "reset_rodada")
    assert reset is not None, "snapshot em rodada 2+ deve emitir reset_rodada (B7)"
    partida = lobby.partidas[-1]
    esperado = [j.dados_qtd for j in partida.jogadores]
    assert reset["jogadores_dados_qtd"] == esperado, f"{reset['jogadores_dados_qtd']} != {esperado}"
    assert len(set(reset["jogadores_dados_qtd"])) > 1, "contagens devem refletir a perda de dados"
    assert reset["jogadores_nomes"] == [j.username for j in partida.jogadores]
    c4.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("B1/B7 (desconexão na conferência)")


def teste_conferencia_perdedor_desconectado():
    # O perdedor da rodada cai ainda na conferência: ele já foi removido da
    # partida, mas `rodada.perdedor` continua apontando para ele. Ao fechar a
    # conferência, `verificar_partida_anterior` tentava remover de novo (e
    # decrementar dos dados) um jogador que não está mais na partida — o que
    # travaria a rodada seguinte.
    _limpar()
    clis, _ = _conectar_trio(1)
    lobby = _rodada_ate_conferencia(clis)
    rodada = lobby.partidas[-1].rodadas[-1]
    perdedor = rodada.perdedor
    assert perdedor is not None
    clis[perdedor.username][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.partidas[-1].jogadores) == 2, "perdedor caído deve sair da partida"

    for c, chave in clis.values():
        if c.is_connected():
            c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1, "a rodada seguinte deve começar mesmo sem o perdedor"
    assert len(lobby.partidas[-1].rodadas) == 2, "deve ter criado a rodada 2"
    _desconectar_todos(clis)
    _limpar()
    _ok("perdedor desconectado na conferência")


def teste_b2_desconexao_vitoria():
    _limpar()
    clis, _ = _conectar_trio(1)
    _rodada_ate_conferencia(clis)
    for c, chave in clis.values():
        c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert len(partida.jogadores) == 2 and lobby.pagina == 1

    for c, chave in clis.values():
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    _rodada_ate_conferencia(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 4, f"deve estar na vitória, página={lobby.pagina}"
    assert partida.vencedor_final is not None
    assert len(lobby.jogadores) == 3, "todos seguem no lobby (incluindo eliminados)"

    # B2: um eliminado confirma a vitória e cai; o contador deve ser desfeito.
    vencedor = partida.vencedor_final
    quem_confirma = next(nome for nome in ("Caio", "Bia", "Ana") if nome != vencedor.username)
    clis[quem_confirma][0].emit("vencedor_final", {"chave": clis[quem_confirma][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.conferiram_vencedor == 1
    clis[quem_confirma][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.conferiram_vencedor == 0, "confirmação do desconectado deve ser desfeita (B2)"
    assert len(lobby.jogadores) == 2

    for j in lobby.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera", "vitória confirmada deve resetar o lobby"
    _desconectar_todos(clis)
    _limpar()
    _ok("B2 (desconexão na vitória)")


def teste_b4_vencedor_por_desconexao():
    _limpar()
    clis, _ = _conectar_trio(1)
    clis["Bia"][0].disconnect()
    clis["Caio"][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.vencedor_final is not None, "vencedor deve ser declarado por desconexão"
    assert lobby.pagina == 4
    vencedor = partida.vencedor_final
    cli_venc, chave_venc = clis[vencedor.username]
    cli_venc.emit("foguetear_click", {"chave": chave_venc})
    eventos = cli_venc.get_received()
    assert _achar_evento(eventos, "soltar_fogos") is not None, "vencedor deve soltar fogos (B4)"
    _desconectar_todos(clis)
    _limpar()
    _ok("B4 (vencedor por desconexão)")


# --- Fase 7 -----------------------------------------------------------------
def teste_a3_a6_chave_e_idempotencia():
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    for c, nome in ((c1, "Ana"), (c2, "Bia")):
        c.emit("apelido", {"apelido_msg": nome})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})

    c1.emit("iniciar_partida", {"chave": "errada", "dados_qtd": 2})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.status == "espera", "iniciar_partida sem chave correta não pode iniciar (A3)"
    assert lobby.pagina == 0

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 2})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    assert all(j.joguei_dados is False for j in lobby.jogadores)

    c1.emit("jogar_dados", {"chave": "errada"})
    eventos = c1.get_received()
    assert _achar_evento(eventos, "jogar_dados_resultado") is None, "chave errada deve ser ignorada (A3)"

    c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    assert _contar_eventos(eventos, "jogar_dados_resultado") == 1, "deve rolar exatamente uma vez"
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    dados_apos = list(ana.dados)
    assert ana.joguei_dados is True

    c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    assert _contar_eventos(eventos, "jogar_dados_resultado") == 1, "segundo jogar_dados reentrega o resultado (A6/reenvio idempotente)"
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.dados == dados_apos, "dados não podem mudar num re-rolar (A6)"

    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("A3/A6 (chave e idempotência)")


def teste_autenticar_comparacao_constant_time():
    """
    Fase 36 (S1): `autenticar` compara a chave com `hmac.compare_digest`
    (constant-time) em vez de `!=`. Comportamento idêntico ao anterior, inclusive
    com payload malformado ({'chave': None} ou não-string): aborto silencioso,
    nunca exceção no handler.
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})

    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"nome": "Mesa"}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.nome == "Mesa", "chave correta deve passar (S1)"

    c1.emit("configurar_partida", {"chave": "errada",
                                   "config": {"nome": "Hackeada"}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.nome == "Mesa", "chave errada não pode mutar (S1)"

    for chave_invalida in (None, 123, ["x"]):
        c1.emit("configurar_partida", {"chave": chave_invalida,
                                       "config": {"nome": "Hackeada"}})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.nome == "Mesa", \
            f"chave malformada {chave_invalida!r} não pode mutar (S1)"

    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("S1 (autenticar com comparação constant-time)")


def teste_v3_payloads_malformados():
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    for c, nome in ((c1, "Ana"), (c2, "Bia")):
        c.emit("apelido", {"apelido_msg": nome})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})

    c1.emit("apelido", None)
    c1.emit("iniciar_partida", "texto qualquer")
    c1.emit("iniciar_partida", None)
    c1.emit("configurar_partida", None)
    c1.emit("ficar_pronto", None)
    c1.emit("listar_partidas", None)
    c1.emit("jogar_dados", None)
    c1.emit("joguei_dados", None)
    c1.emit("apostar", None)
    c1.emit("apostar", {"dados": "não é dict"})
    c1.emit("desconfiar", None)
    c1.emit("conferencia_final", None)
    c1.emit("vencedor_final", None)
    c1.emit("foguetear_click", None)

    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.status == "espera"
    assert all(j.joguei_dados is False for j in lobby.jogadores)

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    for c, chave in ((c1, cs1["chave_secreta"]), (c2, cs2["chave_secreta"])):
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in ((c1, cs1["chave_secreta"]), (c2, cs2["chave_secreta"])):
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2

    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("V3 (payloads malformados)")


def teste_v2_cooldown():
    _sleep_real = time.sleep
    sid_teste = "sid-cooldown"
    assert funcoes_gerais.tem_cooldown(sid_teste, 0.5) is False
    assert funcoes_gerais.tem_cooldown(sid_teste, 0.5) is True

    _limpar()
    modulo_app.tem_cooldown = funcoes_gerais.tem_cooldown
    try:
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        _sleep_real(0.6)
        c2.emit("apelido", {"apelido_msg": "Bia"})
        _sleep_real(0.6)
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        _sleep_real(0.6)
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 1
        _sleep_real(0.6)

        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        eventos = c1.get_received()
        assert _contar_eventos(eventos, "jogar_dados_resultado") == 1, "segundo emit cai no cooldown (V2)"

        _sleep_real(0.6)
        c2.emit("jogar_dados", {"chave": cs2["chave_secreta"]})
        _sleep_real(0.6)
        c1.emit("joguei_dados", {"chave_secreta": cs1["chave_secreta"]})
        _sleep_real(0.6)
        c2.emit("joguei_dados", {"chave_secreta": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 2
        c1.disconnect()
        c2.disconnect()
    finally:
        modulo_app.tem_cooldown = lambda *a, **k: False
    _limpar()
    _ok("V2 (cooldown)")


def teste_conferencia_ok_sem_cooldown():
    """
    O "Ok" da conferência não pode ser derrubado pelo cooldown de escrita (0,5s).

    Quando o humano desconfia (a tela de conferência abre na hora, sem atraso de
    narração) e confirma logo em seguida, o drop silencioso do `conferencia_final`
    pelo cooldown deixava a partida presa na conferência — e o botão já tinha sido
    desabilitado no cliente, sem como recuperar. A confirmação é idempotente
    (`confirmou_rodada`) e espaçada pelo fluxo do jogo, então não passa pelo
    cooldown anti-spam.
    """
    _limpar()
    modulo_app.tem_cooldown = funcoes_gerais.tem_cooldown
    _sleep_real = time.sleep
    try:
        c1, cs1, _ = _conectar()
        chave = cs1["chave_secreta"]
        c1.emit("apelido", {"apelido_msg": "Ana"})
        _sleep_real(0.6)
        c1.emit("adicionar_ia", {"chave": chave, "nivel": 2, "quantidade": 4})
        _sleep_real(0.6)
        c1.emit("iniciar_partida", {"chave": chave, "dados_qtd": 3})
        _sleep_real(0.6)

        def _estado():
            lobby = modulo_store.carregar_sala(SALA)
            partida = lobby.partidas[-1]
            rodada = partida.rodadas[-1]
            humano = next(j for j in lobby.jogadores if not j.is_ia)
            return lobby, partida, rodada, humano

        desconfiou = False
        for _ in range(400):
            lobby, partida, rodada, humano = _estado()
            if lobby.status == "espera":
                break
            if lobby.pagina == 1:
                c1.emit("jogar_dados", {"chave": chave})
                _sleep_real(0.6)
                c1.emit("joguei_dados", {"chave_secreta": chave})
                _sleep_real(0.6)
            elif lobby.pagina == 2:
                if rodada.vez_atual is humano and rodada.turnos:
                    # O humano desconfia: o cooldown dele fica "fresco" para o OK.
                    c1.emit("desconfiar", {"dados": {"chave": chave}})
                    desconfiou = True
                    break
                elif rodada.vez_atual is humano:
                    c1.emit("apostar", {"dados": {"chave": chave, "dado": 1, "quantidade": 1}})
                    _sleep_real(0.6)
                else:
                    # Vez de IA parada: o heartbeat destrava a fila das IAs.
                    c1.emit("heartbeat", {"chave": chave})
                    _sleep_real(0.6)
            elif lobby.pagina == 3:
                c1.emit("conferencia_final", {"chave": chave})
                _sleep_real(0.6)
            elif lobby.pagina == 4:
                c1.emit("vencedor_final", {"chave": chave})
                _sleep_real(0.6)

        assert desconfiou, "o humano não chegou a desconfiar para testar o OK imediato"

        # Confirma sem nenhuma pausa: o OK logo após o desconfiar não pode ser dropado.
        c1.emit("conferencia_final", {"chave": chave})
        lobby, partida, rodada, humano = _estado()
        assert lobby.pagina != 3, "OK imediato após desconfiar ficou preso na conferência"
        assert lobby.pagina in (1, 4), f"deve avançar para a próxima rodada, página={lobby.pagina}"
        c1.disconnect()
    finally:
        modulo_app.tem_cooldown = lambda *a, **k: False
    _limpar()
    _ok("OK da conferência não é dropado pelo cooldown")


def teste_a4_a5_lock_e_sorteio():
    _limpar()
    clis, lobby = _conectar_trio(1)
    partida = lobby.partidas[-1]
    assert partida.jogador_sorteado in partida.jogadores, "jogador_sorteado deve ser membro (A5)"
    _rodada_ate_conferencia(clis)
    _desconectar_todos(clis)
    _limpar()
    _ok("A4/A5 (lock e sorteio)")


def teste_partida_completa():
    _limpar()
    clis, lobby = _conectar_trio(1)
    partida = lobby.partidas[-1]
    _rodada_ate_conferencia(clis)
    narracoes = [e for e in clis[partida.jogadores[0].username][0].get_received()
                 if e["name"] == "narracao"]
    assert narracoes, "a partida deve emitir narracao"
    assert narracoes[0]["args"][0].get("segmentos"), "narracao deve trazer segmentos i18n"
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 1 and len(partida.jogadores) == 2

    for j in partida.jogadores:
        clis[j.username][0].emit("jogar_dados", {"chave": clis[j.username][1]})
    for j in partida.jogadores:
        clis[j.username][0].emit("joguei_dados", {"chave_secreta": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    _rodada_ate_conferencia(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 4, f"vencedor declarado, página={lobby.pagina}"
    vencedor = partida.vencedor_final
    assert vencedor is not None

    cli_venc, chave_venc = clis[vencedor.username]
    cli_venc.emit("foguetear_click", {"chave": "errada"})
    assert _achar_evento(cli_venc.get_received(), "soltar_fogos") is None
    cli_venc.emit("foguetear_click", {"chave": chave_venc})
    assert _achar_evento(cli_venc.get_received(), "soltar_fogos") is not None

    for j in lobby.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera"
    _desconectar_todos(clis)
    _limpar()
    _ok("partida completa (Fases 6/7)")


def teste_gate_pagina_confirmacoes():
    _limpar()
    clis, lobby = _conectar_trio(1)  # 3 jogadores, página 2 (turnos)
    assert lobby.pagina == 2

    # Fase 15: confirmar a conferência durante os turnos não pode adiantar a rodada.
    for c, chave in clis.values():
        c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 2, f"gate: conferência precoce não pode sair dos turnos (pagina={lobby.pagina})"
    assert len(partida.rodadas) == 1, "gate: turnos não podem criar nova rodada"
    assert all(not j.confirmou_rodada for j in partida.jogadores)

    # Fase 15: confirmar a vitória durante os turnos não pode resetar o lobby.
    for j in partida.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2 and lobby.status == "jogando", "gate: vitória precoce não pode resetar"
    assert lobby.conferiram_vencedor == 0, "gate: contador de vitória não pode subir nos turnos"

    _desconectar_todos(clis)
    _limpar()
    _ok("gate de página das confirmações (B1)")


def teste_espectador_nao_e_jogador():
    _limpar()
    clis, lobby = _conectar_trio(1)  # 3 jogadores, página 2
    assert len(lobby.jogadores) == 3 and not lobby.espectadores

    c4, _, eventos4 = _conectar()  # entra no meio da partida
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert len(lobby.jogadores) == 3, "espectador não pode virar jogador do lobby (B2)"
    assert len(lobby.espectadores) == 1, "espectador deve ir para lobby.espectadores"
    assert all(j not in partida.jogadores for j in lobby.espectadores)
    assert _achar_evento(eventos4, "espectador") is not None, "snapshot deve marcar ESPECTADOR"

    # Duas desistências declaram o terceiro vencedor. O espectador não entra na
    # conta da vitória (len(lobby.jogadores)).
    for nome in ("Bia", "Caio"):
        clis[nome][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.vencedor_final is not None
    assert len(lobby.jogadores) == 1, "só o vencedor humano resta no lobby"
    assert len(lobby.espectadores) == 1

    vencedor = partida.vencedor_final
    clis[vencedor.username][0].emit("vencedor_final", {"chave": clis[vencedor.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera", "vitória deve resetar com 1 jogador"
    # O espectador é promovido a jogador na próxima partida, sem duplicar.
    assert not lobby.espectadores, "espectadores devem ser promovidos no reset"
    assert len(lobby.jogadores) == 2

    c4.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("espectador não é jogador (B2)")


def teste_sala_so_com_bot_e_removida():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert any(j.is_ia for j in lobby.jogadores)

    # Fase 15: um bot não conta como "outro ativo" — o humano sai na hora e a
    # sala (só com bots) é removida em vez de ficar órfã na janela de graça.
    c1.disconnect()
    assert modulo_store.carregar_sala(SALA) is None, "sala só com bots deve ser removida (B3)"
    _limpar()
    _ok("sala só com bot é removida (B3)")


def teste_gc_unificado_sala_bot_sem_humano():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.resumo_partida()["humanos"] == 1, "resumo deve contar o humano conectado"
    # Simula uma instância serverless que morreu sem disconnect: o humano some
    # da sala e sobra só o bot persistido (nenhum humano conectado).
    lobby.jogadores = [j for j in lobby.jogadores if j.is_ia]
    modulo_store.salvar_sala(lobby)
    c1.disconnect()
    assert modulo_store.carregar_sala(SALA) is not None, "pré-condição: sala só com bot persistida"

    # O próximo connect no mesmo código passa pelo GC unificado: fecha o fantasma
    # e recria a sala do zero, com o novo humano como master (sem bots antigos).
    c2, cs2, _ = _conectar()
    novo = modulo_store.carregar_sala(SALA)
    assert novo is not None
    assert len(novo.jogadores) == 1 and not novo.jogadores[0].is_ia, \
        "GC deve recriar a sala sem os bots antigos"
    assert novo.jogadores[0].master, "o novo humano vira master da sala recriada"
    c2.disconnect()
    _limpar()
    _ok("GC unificado fecha/reabre sala só com bot (sem humano conectado)")


def teste_busca_esconde_sala_sem_humano():
    from datetime import datetime, timedelta
    agora = datetime.now().isoformat()
    velho = (datetime.now() - timedelta(seconds=9999)).isoformat()
    resumos = [
        ("b0t", {"sala": "b0t", "publica": True, "jogadores": 2, "humanos": 0,
                 "visto_em": agora}),
        ("hum4", {"sala": "hum4", "publica": True, "jogadores": 2, "humanos": 1,
                  "visto_em": agora}),
        ("l3g4", {"sala": "l3g4", "publica": True, "jogadores": 2, "visto_em": agora}),
        # Fantasma do serverless: humanos=1 congelado de uma instância morta.
        ("gz00", {"sala": "gz00", "publica": True, "jogadores": 2, "humanos": 1,
                  "visto_em": velho}),
        # Formato antigo, sem `visto_em`: tratado como morto (limpa os fantasmas).
        ("antg", {"sala": "antg", "publica": True, "jogadores": 2, "humanos": 1}),
    ]
    for sala_id, resumo in resumos:
        modulo_store.salvar_resumo(sala_id, dict(resumo))
    try:
        salas = {r.get("sala") for r in funcoes_gerais.listar_resumos_partidas({})}
        assert "b0t" not in salas, "sala sem humano conectado não pode aparecer na busca"
        assert "hum4" in salas, "sala com humano conectado e viva deve aparecer"
        assert "l3g4" in salas, "resumo antigo sem 'humanos' cai no total de jogadores"
        assert "gz00" not in salas, "resumo parado (sem heartbeat) não pode aparecer"
        assert "antg" not in salas, "resumo sem 'visto_em' é fantasma e não pode aparecer"
    finally:
        for sala_id, _ in resumos:
            modulo_store.remover_resumo(sala_id)
    _ok("busca esconde sala sem humano conectado")


def teste_heartbeat_renova_resumo():
    from datetime import datetime, timedelta
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    # Envelhece o resumo como se a sala tivesse parado (instância morta).
    lobby = modulo_store.carregar_sala(SALA)
    lobby.visto_em = datetime.now() - timedelta(seconds=9999)
    modulo_store.salvar_resumo(SALA, lobby.resumo_partida())
    salas = {r.get("sala") for r in funcoes_gerais.listar_resumos_partidas({})}
    assert SALA not in salas, "pré-condição: resumo parado está escondido"

    c1.emit("heartbeat", {"chave": cs1["chave_secreta"]})
    salas = {r.get("sala") for r in funcoes_gerais.listar_resumos_partidas({})}
    assert SALA in salas, "heartbeat deve renovar o visto_em e reexibir a sala"
    c1.disconnect()
    _limpar()
    _ok("heartbeat renova o resumo da busca")


def teste_heartbeat_resincroniza_lobby():
    # Fase 18/19/E: as rooms/emits do Socket.IO vivem por instância; quem
    # entrou/ficou pronto numa instância diferente não alcança o broadcast do
    # host. O heartbeat na sala de espera devolve o snapshot atual do lobby
    # (lido do store compartilhado) direcionado a cada cliente; quando o master
    # inicia a partida e o `mudar_pagina` fica na instância dele, o heartbeat
    # também empurra o cliente atrasado para a página autoritativa.
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.get_received()  # descarta o broadcast local (que não existiria entre instâncias)

    c1.emit("heartbeat", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    atualizacoes = [e for e in eventos if e["name"] == "update_user_list"]
    assert atualizacoes, "heartbeat na espera deve responder com update_user_list"
    payload = atualizacoes[-1]["args"][0]
    assert payload.get("users") == ["Ana", "Bia"], \
        f"host deve ver o jogador da outra instância: {payload.get('users')}"
    assert payload.get("prontos") == [False, True], \
        f"host deve ver a prontidão da outra instância: {payload.get('prontos')}"
    assert payload.get("status") == "espera"

    # Fase E: partida iniciada, o cliente ainda na página 0 (atrasado, preso
    # noutra instância) é empurrado para a página 1 pelo heartbeat.
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    c1.get_received()
    c1.emit("heartbeat", {"chave": cs1["chave_secreta"], "pagina": 0})
    eventos = c1.get_received()
    assert all(e["name"] != "update_user_list" for e in eventos), \
        "heartbeat em partida não deve re-emitir a lista da espera"
    mudancas = [e for e in eventos if e["name"] == "mudar_pagina"]
    assert mudancas and mudancas[-1]["args"][0]["pag_numero"] == 1, \
        "heartbeat deve empurrar o cliente atrasado para a página 1"

    # Já na página certa, o heartbeat não precisa re-emitir mudar_pagina.
    c1.get_received()
    c1.emit("heartbeat", {"chave": cs1["chave_secreta"], "pagina": 1})
    eventos = c1.get_received()
    assert all(e["name"] != "mudar_pagina" for e in eventos), \
        "heartbeat na página certa não deve re-emitir mudar_pagina"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("heartbeat re-sincroniza o lobby entre instâncias")


def teste_heartbeat_espera_fresco_entre_instancias():
    # Fase E2 (regra de impedimento): o re-sync da sala de espera não pode
    # depender do cache tolerante a defasagem (Fase C). Na Vercel, com o cache
    # velho da própria instância, o host não via quem entra/fica pronto e o
    # jogador não-master ficava preso na página 0 quando o master iniciava — o
    # `mudar_pagina` ficava na instância do host e o início da partida só era
    # detectado quando o cache expirava (até ~45s). Simula a instância com o
    # cache congelado (outra instância não sabe do que aconteceu) e exige que o
    # heartbeat recarregue do store compartilhado a cada batida da espera.
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    lobby_so_ana = modulo_store.Lobby.de_dict(modulo_store.carregar_sala(SALA).para_dict())

    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    # Cache da instância do host congelado ANTES de Bia entrar.
    with modulo_store._cache_salas_guard:
        modulo_store._cache_salas[SALA] = (lobby_so_ana, time.monotonic())

    c1.get_received()
    c1.emit("heartbeat", {"chave": cs1["chave_secreta"], "pagina": 0})
    eventos = c1.get_received()
    atualizacoes = [e for e in eventos if e["name"] == "update_user_list"]
    assert atualizacoes, "heartbeat na espera deve responder com update_user_list"
    payload = atualizacoes[-1]["args"][0]
    assert payload.get("users") == ["Ana", "Bia"], \
        f"host deve ver o jogador da outra instância mesmo com cache velho: {payload.get('users')}"
    assert payload.get("prontos") == [False, True], \
        f"host deve ver a prontidão mesmo com cache velho: {payload.get('prontos')}"

    # Partida inicia: congela o cache da instância do jogador no estado da espera.
    lobby_pre = modulo_store.Lobby.de_dict(modulo_store.carregar_sala(SALA).para_dict())
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1 and lobby.status == "jogando"
    with modulo_store._cache_salas_guard:
        modulo_store._cache_salas[SALA] = (lobby_pre, time.monotonic())

    c2.get_received()
    c2.emit("heartbeat", {"chave": cs2["chave_secreta"], "pagina": 0})
    eventos = c2.get_received()
    mudancas = [e for e in eventos if e["name"] == "mudar_pagina"]
    assert mudancas and mudancas[-1]["args"][0]["pag_numero"] == 1, \
        "jogador da outra instância deve ir para a página 1 mesmo com cache velho"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("heartbeat da espera lê fresco do store entre instâncias")


def teste_sala_orfa_e_fechada():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    assert modulo_store.carregar_sala(SALA) is not None

    # Ana cai: fica na janela de graça porque Bia segue ativa.
    c1.disconnect()
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby is not None
    assert any(j.desconectado_em is not None for j in lobby.jogadores)

    # Bia cai: não resta humano ATIVO (Ana é fantasma na graça), então a sala
    # precisa fechar em vez de ficar persistida sem ninguém conectado.
    c2.disconnect()
    assert modulo_store.carregar_sala(SALA) is None, "sala sem humano ativo deve fechar"

    # Resumo de sala vazia não pode aparecer na busca.
    modulo_store.salvar_resumo("orfa", {"sala": "orfa", "publica": True, "jogadores": 0})
    try:
        resumos = funcoes_gerais.listar_resumos_partidas({})
        assert all(r.get("sala") != "orfa" for r in resumos), "sala vazia não pode ser listada"
    finally:
        modulo_store.remover_resumo("orfa")
    _limpar()
    _ok("sala órfã (sem humano ativo) é fechada")


def teste_sala_padrao_fica_na_home():
    # Fase 18: sem código (ou com `?sala=padrao`/inválido), o connect NÃO cria
    # sala automaticamente — o cliente fica na home e decide criar ou buscar.
    _limpar()
    modulo_store.remover_sala(funcoes_gerais.SALA_PADRAO)
    c1 = socketio.test_client(app, query_string="sala=padrao")
    eventos = c1.get_received()
    assert _achar_evento(eventos, "sala_criada") is None, \
        "home não pode criar sala automaticamente"
    cs = _achar_evento(eventos, "connect_start")
    assert cs is not None, "home deve receber connect_start"
    assert not cs.get("sala"), "home não pode estar em nenhuma sala"
    assert modulo_store.carregar_sala(funcoes_gerais.SALA_PADRAO) is None, \
        "a sala padrão não pode ser materializada"
    c1.disconnect()

    # Código inválido também cai na home (normalizar_sala usa o sentinela).
    c2 = socketio.test_client(app, query_string="sala=invalida!")
    eventos2 = c2.get_received()
    assert _achar_evento(eventos2, "sala_criada") is None
    assert not _achar_evento(eventos2, "connect_start").get("sala")
    c2.disconnect()

    # "Criar sala" (evento) devolve um código novo que funciona como sala normal.
    c3 = socketio.test_client(app, query_string="sala=padrao")
    c3.get_received()  # descarta o connect_start da home
    c3.emit("criar_sala")
    criada = _achar_evento(c3.get_received(), "sala_criada")
    assert criada and criada.get("sala"), "criar_sala deve devolver um código"
    assert criada["sala"] != funcoes_gerais.SALA_PADRAO
    nova = criada["sala"]
    c4 = socketio.test_client(app, query_string=f"sala={nova}")
    eventos4 = c4.get_received()
    assert _achar_evento(eventos4, "connect_start") is not None
    assert modulo_store.carregar_sala(nova) is not None
    c4.disconnect()
    modulo_store.remover_sala(nova)
    _limpar()
    _ok("home não cria sala automaticamente (Fase 18)")


def teste_aposta_fora_da_pagina():
    # Fase 15: apostar/desconfiar só valem na tela de turnos (2). Depois da
    # desconfiança (página 3), a vez ainda é do desconfiador; sem o gate ele
    # conseguiria criar um turno novo e corromper a rodada em conferência.
    _limpar()
    clis, _ = _conectar_trio(1)
    lobby = _rodada_ate_conferencia(clis)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert lobby.pagina == 3
    vez = rodada.vez_atual
    ultimo = rodada.turnos[-1]
    cli_vez, chave_vez = clis[vez.username]
    turnos_antes = len(rodada.turnos)
    # Aposta que seria legal (mesma face com quantidade maior): sem o gate,
    # criaria um turno.
    cli_vez.emit("apostar", {"dados": {"chave": chave_vez,
                                       "dado": ultimo.dado_face, "quantidade": ultimo.dado_qtd + 1}})
    cli_vez.emit("desconfiar", {"dados": {"chave": chave_vez}})
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert lobby.pagina == 3, "aposta/desconfiança fora da página 2 devem ser ignoradas"
    assert len(rodada.turnos) == turnos_antes, "não pode criar turno em conferência"
    assert rodada.vez_atual is vez, "a vez não pode mudar em conferência"
    _desconectar_todos(clis)
    _limpar()
    _ok("gate de página de aposta/desconfiança")


def teste_master_apos_substituicao_ia():
    # Um master que cai e vira bot não pode segurar a flag `master` para sempre
    # (senão nenhum humano consegue mais iniciar a próxima partida).
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"substituir_desconectado_por_ia": True}})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.jogadores[0].username == "Ana" and lobby.jogadores[0].master

    c1.disconnect()
    c2.emit("verificar_desconectados")  # expurga a janela (grace = 0 no teste)
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    bia = next(j for j in lobby.jogadores if j.username == "Bia")
    assert ana.is_ia, "master caído deve ser substituído por IA"
    assert not ana.master, "bot não pode continuar master"
    assert bia.master, "outro humano deve assumir o master"
    assert lobby.verificar_jogador_master(), "deve haver um master humano"
    assert lobby.retornar_master() is bia, "o master retornado não pode ser o bot"
    c2.disconnect()
    _limpar()
    _ok("master não fica preso em bot substituído")


def teste_espectador_segura_grace():
    # Um espectador humano conectado mantém a sala viva: o jogador que cai
    # deve ganhar a janela de reconexão (e não ser removido na hora).
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    c2, _, ev2 = _conectar()  # entra no meio: espectador humano
    assert _achar_evento(ev2, "espectador") is not None

    c1.disconnect()  # só resta o bot (jogador) e o espectador humano
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby is not None
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.desconectado_em is not None, "espectador humano deve segurar a janela de graça"
    c2.disconnect()
    _limpar()
    _ok("espectador humano segura a janela de graça")


def teste_sala_sem_jogadores_promove_espectador():
    # Partida em andamento sem nenhum jogador restante, mas com um espectador
    # humano: o GC deve devolver a sala à espera e promover o espectador, senão
    # ela fica presa em "jogando" e ninguém mais consegue jogar.
    import modelos
    emit_salvo = _salvar_emit()
    _silenciar_emit()  # fora de request não há room/namespace
    try:
        modulo_store.remover_sala(SALA)
        lobby = modelos.Lobby(sala_id=SALA, lobby_numero=1)
        lobby.pagina = 4
        lobby.status = "jogando"
        espectador = modelos.Jogador(client_id="esp")
        espectador.username = "Esp"
        lobby.espectadores.append(espectador)
        modulo_store.salvar_sala(lobby)

        fechou = modulo_app._gc_sala(lobby)
        assert fechou is False, "sala com humano conectado não pode ser fechada"
        recarregado = modulo_store.carregar_sala(SALA)
        assert recarregado.status == "espera" and recarregado.pagina == 0
        assert not recarregado.espectadores, "espectador deve ser promovido"
        assert len(recarregado.jogadores) == 1
        assert recarregado.jogadores[0].username == "Esp"
        assert recarregado.jogadores[0].master, "promovido deve virar master"
    finally:
        _restaurar_emit(emit_salvo)
        _limpar()
    _ok("sala sem jogadores promove espectador ao lobby")


def teste_config_nome_roundtrip():
    # O input do master lê `config.nome`, mas o nome vive no Lobby: o payload de
    # config precisa carregá-lo ou o campo é limpo a cada atualização.
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.get_received()  # descarta os eventos do connect/apelido
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"nome": "Sala do Fbi"}})
    eventos = c1.get_received()
    listas = [e for e in eventos if e["name"] == "update_user_list"]
    assert listas, "configurar_partida deve atualizar a lista"
    config = listas[-1]["args"][0].get("config", {})
    assert config.get("nome") == "Sala do Fbi", \
        "o cliente precisa receber config.nome para manter o input do master"
    c1.disconnect()
    _limpar()
    _ok("nome da partida no payload de config")


def teste_resumo_malformado_nao_quebra_busca():
    _limpar()
    modulo_store.salvar_resumo("quebrado", {"sala": "quebrado", "publica": True})
    try:
        for ordenar in ("jogadores", "nome", "recentes"):
            funcoes_gerais.listar_resumos_partidas({"ordenar": ordenar})
    except Exception as erro:  # noqa: BLE001
        raise AssertionError(f"resumo malformado não pode quebrar a busca: {erro!r}")
    finally:
        modulo_store.remover_resumo("quebrado")
    _ok("resumo malformado na busca (B6)")


def teste_cooldown_expurga_antigos():
    with funcoes_gerais._cooldowns_guard:
        funcoes_gerais._cooldowns.clear()
        agora = funcoes_gerais.time.time()
        for i in range(5000):
            funcoes_gerais._cooldowns[f"antigo{i}"] = agora - 120
    try:
        assert funcoes_gerais.tem_cooldown("novo", 0.5) is False
        with funcoes_gerais._cooldowns_guard:
            restantes = len(funcoes_gerais._cooldowns)
        assert restantes < 5000, "cooldowns antigos devem ser expurgados (B8)"
    finally:
        with funcoes_gerais._cooldowns_guard:
            funcoes_gerais._cooldowns.clear()
    _ok("cooldown com expurgo (B8)")


def teste_poda_partidas():
    import modelos
    emit_salvo = _salvar_emit()
    _silenciar_emit()  # fora de request não há room/namespace
    try:
        lobby = modelos.Lobby(sala_id="poda", lobby_numero=1)
        for cid, nome in (("a", "A"), ("b", "B")):
            jogador = modelos.Jogador(client_id=cid)
            jogador.username = nome
            lobby.adicionar_jogador(jogador)
        lobby.jogadores[0].master = True
        p1 = lobby.construir_partida(dados_qtd=1)
        assert p1.partida_num == 1
        lobby.resetar_para_lobby()
        p2 = lobby.construir_partida(dados_qtd=1)
        assert p2.partida_num == 2, "numeração deve continuar após a poda"
        lobby.resetar_para_lobby()
        assert len(lobby.partidas) <= 1, "histórico antigo deve ser podado"
        copia = modelos.Lobby.de_dict(lobby.para_dict())
        assert copia.proxima_partida_num == 3, "numeração deve sobreviver ao round-trip"
    finally:
        _restaurar_emit(emit_salvo)
    _ok("poda de partidas antigas")


def teste_json_tamanho_bounded():
    """
    Fase 52: a poda do histórico (`resetar_para_lobby` mantém só a última
    partida) + o tamanho por rodada mantêm o JSON persistido longe do limite de
    payload da Upstash. Roda 100 rodadas REAIS (motor `construir_rodada`, com
    turnos típicos) e verifica que o blob fica bem abaixo de 500KB e que o
    round-trip de serialização segue válido com o histórico acumulado.
    """
    import json as _json
    import modelos
    emit_salvo = _salvar_emit()
    _silenciar_emit()
    try:
        lobby = modelos.Lobby(sala_id="tamanho", lobby_numero=1)
        for cid, nome in (("a", "A"), ("b", "B")):
            jogador = modelos.Jogador(client_id=cid)
            jogador.username = nome
            lobby.adicionar_jogador(jogador)
        lobby.jogadores[0].master = True
        partida = lobby.construir_partida(dados_qtd=3)
        partida.construir_rodada()  # rodada 1
        perdedor, vencedor = partida.jogadores
        for _ in range(99):
            ultima = partida.rodadas[-1]
            ultima.perdedor = perdedor
            ultima.vencedor = vencedor
            perdedor.dados_qtd = 3  # recompõe o dado perdido: nunca elimina
            partida.construir_rodada()
        assert len(partida.rodadas) == 100, "deve acumular 100 rodadas"
        # Turnos típicos (poucos por rodada, como numa partida real) para o blob
        # refletir tamanho de jogo, não só a rolagem.
        for rodada in partida.rodadas:
            for i, jogador in enumerate(partida.jogadores):
                rodada.turnos.append(modelos.Turno(
                    da_rodada=rodada, dado=(i % 6) + 1, jogador=jogador,
                    dado_qtd=2, turno_numero=i + 1))
        blob = lobby.para_dict()
        tamanho = len(_json.dumps(blob, ensure_ascii=False).encode("utf-8"))
        assert tamanho < 500_000, \
            f"JSON do Lobby com 100 rodadas deve ficar < 500KB (tinha {tamanho} bytes)"
        copia = modelos.Lobby.de_dict(blob)
        assert len(copia.partidas[0].rodadas) == 100, \
            "round-trip deve preservar o histórico acumulado"
    finally:
        _restaurar_emit(emit_salvo)
    _ok("JSON do Lobby limitado com 100 rodadas (Fase 52)")


def teste_commit_reveal():
    import seed

    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"verificacao_ativa": True}})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    assert modulo_store.carregar_sala(SALA).config["verificacao_ativa"] is True

    # Fase de compromisso: só o hash vai para o servidor (o nonce fica local).
    n1, n2 = seed.gerar_nonce(), seed.gerar_nonce()
    c1.emit("comprometer_seed", {"chave": cs1["chave_secreta"], "compromisso": seed.compromisso(n1)})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.compromisso_seed == seed.compromisso(n1) and ana.nonce_seed is None, \
        "o servidor não pode receber o nonce no commit"
    pode, motivo = lobby.pode_iniciar()
    assert not pode and motivo["chave"] == "msg.motivo.aguardando_revelacao"

    c2.emit("comprometer_seed", {"chave": cs2["chave_secreta"], "compromisso": seed.compromisso(n2)})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.compromissos_completos() and lobby.revelacoes_pendentes()

    # Compromisso imutável: o primeiro vale.
    n1b = seed.gerar_nonce()
    c1.emit("comprometer_seed", {"chave": cs1["chave_secreta"], "compromisso": seed.compromisso(n1b)})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.compromisso_seed == seed.compromisso(n1), "primeiro compromisso deve valer"

    # Fase de revelação (pública: a sala toda recebe os nonces).
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": n1})
    c2.emit("revelar_seed", {"chave": cs2["chave_secreta"], "nonce": n2})
    lobby = modulo_store.carregar_sala(SALA)
    assert not lobby.revelacoes_pendentes(), "todos revelaram"
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.nonce_seed == n1 and ana.revelado_seed
    revelacoes = [e["args"][0] for e in c2.get_received() if e["name"] == "seed_revelacao"]
    assert any(r.get("nonce") == n1 for r in revelacoes), "revelação deve ser pública"

    # Nonce errado é rejeitado (revelação não pode mentir).
    ana.revelado_seed = False
    ana.nonce_seed = None
    modulo_store.salvar_sala(lobby)
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": seed.gerar_nonce()})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert not ana.revelado_seed, "nonce que não bate com o compromisso deve ser recusado"
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": n1})

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.seed_info and partida.seed_final
    assert partida.seed_info["fonte"] == "servidor", "entropia secreta do servidor"
    assert partida.seed_info["entropia_externa"] == partida.seed_info["nonce_servidor"]
    assert all(not p["sem_reveal"] for p in partida.seed_info["participantes"]), \
        "todos revelaram: nada pode cair no fallback"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("commit-reveal (nonce só na revelação)")


def teste_revelar_seed_fora_do_cooldown():
    """
    O `revelar_seed` não pode ser derrubado pelo cooldown de escrita (0,5s).

    No navegador, o cliente compromete e, quando o servidor emite `seed_revelar`
    (assim que todos comprometeram), revela logo em seguida — tudo dentro da
    janela do cooldown. O drop silencioso do `revelar_seed` deixava
    `pode_iniciar` preso em "aguardando_revelacao" para sempre, com todos os
    jogadores prontos e o master sem conseguir iniciar a partida. A revelação é
    idempotente (valida contra o compromisso) e espaçada pelo fluxo do jogo,
    então não passa pelo cooldown anti-spam.
    """
    import seed

    _limpar()
    modulo_app.tem_cooldown = funcoes_gerais.tem_cooldown
    _sleep_real = time.sleep
    try:
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        _sleep_real(0.6)
        c2.emit("apelido", {"apelido_msg": "Bia"})
        _sleep_real(0.6)
        c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                       "config": {"verificacao_ativa": True}})
        _sleep_real(0.6)
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        _sleep_real(0.6)

        n1, n2 = seed.gerar_nonce(), seed.gerar_nonce()
        # Compromete sem pausa e revela assim que o servidor pedir (fluxo real):
        # com cooldown ativo, um `revelar_seed` dropado aqui travaria o início.
        c1.emit("comprometer_seed", {"chave": cs1["chave_secreta"], "compromisso": seed.compromisso(n1)})
        c2.emit("comprometer_seed", {"chave": cs2["chave_secreta"], "compromisso": seed.compromisso(n2)})
        for cliente, nonce in ((c1, n1), (c2, n2)):
            for evento in cliente.get_received():
                if evento["name"] == "seed_revelar":
                    cliente.emit("revelar_seed", {"chave": cs1["chave_secreta"] if cliente is c1
                                                  else cs2["chave_secreta"], "nonce": nonce})

        lobby = modulo_store.carregar_sala(SALA)
        assert not lobby.revelacoes_pendentes(), \
            "revelação imediata após o commit não pode ser dropada pelo cooldown"
        pode, _ = lobby.pode_iniciar()
        assert pode, "com todos revelados e prontos, o master deve poder iniciar"
        c1.disconnect()
        c2.disconnect()
    finally:
        modulo_app.tem_cooldown = lambda *a, **k: False
    _limpar()
    _ok("revelar_seed não é dropado pelo cooldown")


def teste_upstash_indice_resumos():
    arm = modulo_store.ArmazenamentoUpstash("http://fake", "tok")
    estado = {"dados": {}, "indice": set(), "travas": {}}

    def fake_pipeline(comandos):
        for cmd in comandos:
            op = cmd[0]
            if op == "SET":
                estado["dados"][cmd[1]] = cmd[2]
            elif op == "SADD":
                estado["indice"].add(cmd[2])
            elif op == "DEL":
                estado["dados"].pop(cmd[1], None)
            elif op == "SREM":
                estado["indice"].discard(cmd[2])
        return {"result": "OK"}

    def fake_comando(*args):
        op = args[0]
        if op == "SET":
            # Fase 24: o lock distribuído adquire com SET NX/EX — resposta "OK"
            # só quando a chave está livre (sem isso todo handler mutável
            # abortaria em silêncio num ambiente com o lock ligado).
            if estado["travas"].get(args[1]) is None:
                estado["travas"][args[1]] = args[2]
                return {"result": "OK"}
            return {"result": None}
        if op == "DELEX":
            # Compare-and-del: apaga só se o valor ainda for o token informado.
            if estado["travas"].get(args[1]) == args[3]:
                del estado["travas"][args[1]]
                return {"result": 1}
            return {"result": 0}
        if op == "SMEMBERS":
            return {"result": list(estado["indice"])}
        if op == "MGET":
            return {"result": [estado["dados"].get(k) for k in args[1:]]}
        if op == "SADD":
            estado["indice"].update(args[2:])
            return {"result": len(args) - 2}
        if op == "SREM":
            for item in args[2:]:
                estado["indice"].discard(item)
            return {"result": len(args) - 2}
        return {"result": None}

    arm._pipeline = fake_pipeline
    arm._comando = fake_comando
    arm._varrer_chaves = lambda prefixo: []

    arm.salvar_resumo("s1", {"sala": "s1", "nome": "Um"})
    assert "s1" in estado["indice"], "salvar_resumo deve indexar a sala"
    assert [r["sala"] for r in arm.listar_resumos()] == ["s1"]

    # Resumo expirado sai do índice na listagem (sem SCAN).
    del estado["dados"][arm._chave_resumo("s1")]
    assert arm.listar_resumos() == []
    assert "s1" not in estado["indice"], "resumo expirado deve sair do índice"

    arm.salvar_resumo("s2", {"sala": "s2", "nome": "Dois"})
    arm.remover_resumo("s2")
    assert arm.listar_resumos() == []
    assert "s2" not in estado["indice"], "remover_resumo deve desindexar"
    _ok("índice de resumos da Upstash")


def teste_trava_distribuida():
    """
    Fase 24: lock distribuído por sala via Upstash REST — SET NX/EX para
    adquirir e DELEX IFEQ para liberar. Simula duas instâncias compartilhando
    o mesmo Redis (estado fake comum): exclusão mútua, release com token
    errado é no-op, lease expira sozinho e contenda levanta TravaIndisponivel.
    """
    relogio = {"agora": 1_000_000.0}
    estado = {"travas": {}}

    def fake_comando(*args):
        op = args[0]
        if op == "SET":
            chave, valor = args[1], args[2]
            atual = estado["travas"].get(chave)
            if atual is not None and atual[1] > relogio["agora"]:
                return {"result": None}
            restante = args[3:]
            ttl = int(restante[restante.index("EX") + 1]) if "EX" in restante else 0
            estado["travas"][chave] = (valor, relogio["agora"] + ttl)
            return {"result": "OK"}
        if op == "DELEX":
            atual = estado["travas"].get(args[1])
            if atual is not None and atual[1] > relogio["agora"] and atual[0] == args[3]:
                del estado["travas"][args[1]]
                return {"result": 1}
            return {"result": 0}
        if op == "GET":
            atual = estado["travas"].get(args[1])
            if atual is not None and atual[1] <= relogio["agora"]:
                del estado["travas"][args[1]]
                return {"result": None}
            return {"result": atual[0] if atual else None}
        return {"result": None}

    def instancia():
        arm = modulo_store.ArmazenamentoUpstash("http://fake", "tok")
        arm._comando = fake_comando
        return arm

    chave = modulo_store.PREFIXO_TRAVA + "s1"
    a, b = instancia(), instancia()

    # Release com token errado não apaga (DELEX IFEQ é compare-and-del).
    assert a._comando("SET", chave, "tokA", "NX", "EX", 120)["result"] == "OK"
    assert b._comando("DELEX", chave, "IFEQ", "tokErrado")["result"] == 0
    assert a._comando("GET", chave)["result"] == "tokA", "token errado não pode apagar"
    assert b._comando("DELEX", chave, "IFEQ", "tokA")["result"] == 1
    assert a._comando("GET", chave)["result"] is None, "release correto deve liberar"

    # Lease expira sozinho: após a janela, outra instância adquire.
    assert a._comando("SET", chave, "tokB", "NX", "EX", 120)["result"] == "OK"
    relogio["agora"] += 200
    assert b._comando("SET", chave, "tokC", "NX", "EX", 120)["result"] == "OK", \
        "lease expirado deve liberar para outra instância"

    # Exclusão mútua via o context manager + contenda -> TravaIndisponivel.
    original = modulo_store.armazenamento
    tts, espera = modulo_store.TRAVA_TENTATIVAS, modulo_store.TRAVA_ESPERA_BASE
    modulo_store.TRAVA_TENTATIVAS = 2
    modulo_store.TRAVA_ESPERA_BASE = 0.01
    try:
        modulo_store.armazenamento = a
        with modulo_store.trancar_sala_distribuida("s2"):
            assert estado["travas"].get(modulo_store.PREFIXO_TRAVA + "s2") is not None, \
                "acquire deve gravar o token do lock"
            # A instância B (outro processo) não adquire enquanto A segura.
            modulo_store.armazenamento = b
            try:
                with modulo_store.trancar_sala_distribuida("s2"):
                    raise AssertionError("segunda instância não pode adquirir lock ocupado")
            except modulo_store.TravaIndisponivel:
                pass
        # Saiu do `with`: token liberado — uma instância C adquire normalmente.
        modulo_store.armazenamento = instancia()
        with modulo_store.trancar_sala_distribuida("s2"):
            pass
    finally:
        modulo_store.TRAVA_TENTATIVAS = tts
        modulo_store.TRAVA_ESPERA_BASE = espera
        modulo_store.armazenamento = original
    _ok("lock distribuído (SET NX/EX + DELEX IFEQ, exclusão mútua, TTL e contenda)")


def teste_revisao_cas():
    """
    Fase 40 (C6) + Fase 52: o detector CAS de lost-update é um ABORTO — não
    apenas um alerta. `store.salvar_sala` incrementa `Lobby.revisao` a cada
    gravação e, se um lobby STALE (revisão menor que a última salva na
    instância) chegar para persistir, levanta `ConflitoDeEstado` em vez de
    sobrescrever o estado (a Fase 40 logava e corrompia em silêncio). A
    revisão sobrevive ao round-trip e `remover_sala` zera o rastreador.
    """
    import logging
    import modelos
    _limpar()
    lobby = modelos.Lobby(sala_id=SALA, lobby_numero=1)
    lobby.adicionar_jogador(modelos.Jogador(client_id="a"))
    assert lobby.revisao == 1

    # Revisão sobrevive ao round-trip de serialização.
    copia = modelos.Lobby.de_dict(lobby.para_dict())
    assert copia.revisao == lobby.revisao, "revisão deve round-tripar"

    # Cada save incrementa.
    modulo_store.salvar_sala(lobby)
    assert lobby.revisao == 2, "salvar_sala deve incrementar a revisão"
    modulo_store.salvar_sala(lobby)
    assert lobby.revisao == 3

    class _Captura(logging.Handler):
        def __init__(self):
            super().__init__()
            self.registros = []

        def emit(self, record):
            self.registros.append(record.getMessage())

    captura = _Captura()
    logger_store = logging.getLogger('store')
    logger_store.addHandler(captura)
    abortou = False
    try:
        # Save de um lobby stale (revisão regredida = carregado antes do último
        # save) ABORTA com ConflitoDeEstado em vez de sobrescrever.
        lobby.revisao = 1
        try:
            modulo_store.salvar_sala(lobby)
        except modulo_store.ConflitoDeEstado:
            abortou = True
    finally:
        logger_store.removeHandler(captura)
    assert abortou, "save stale deve abortar com ConflitoDeEstado"
    assert any("Fase 52 (CAS)" in m for m in captura.registros), \
        "save stale deve logar o alerta de lost-update"
    assert lobby.revisao == 1, "estado stale não deve ser sobrescrito nem a revisão bumpada"

    # remover_sala limpa o rastreador: recriação recomeça do 1.
    modulo_store.remover_sala(SALA)
    lobby2 = modelos.Lobby(sala_id=SALA, lobby_numero=2)
    modulo_store.salvar_sala(lobby2)
    assert lobby2.revisao == 2, "após remoção a revisão recomeça"
    _limpar()
    _ok("detector CAS aborta save stale (Fase 52)")


def teste_upstash_transporte():
    """
    Fase 41 (C8/C9): transporte HTTPS da Upstash com keep-alive (pool) e 1 retry
    rápido. Contra um servidor HTTP local fake: comandos devolvem o JSON do
    corpo, 5xx transitório é retentado até o sucesso e chamadas sequenciais
    reutilizam a MESMA conexão (keep-alive).
    """
    import http.server
    import threading as _threading

    class _HandlerFake(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        contador = 0
        falhas = 0
        conexoes = set()

        def _enviar_resposta(self, status, corpo):
            self.send_response(status)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _registrar(self):
            type(self).contador += 1
            type(self).conexoes.add(self.connection)

        def do_GET(self):
            self._registrar()
            if type(self).contador <= type(self).falhas:
                self._enviar_resposta(500, b'{"error":"boom"}')
                return
            self._enviar_resposta(200, b'{"result":"ok"}')

        def do_POST(self):
            self._registrar()
            comprimento = int(self.headers.get("Content-Length", 0) or 0)
            if comprimento:
                self.rfile.read(comprimento)
            if type(self).contador <= type(self).falhas:
                self._enviar_resposta(500, b'{"error":"boom"}')
                return
            self._enviar_resposta(200, b'{"result":"ok"}')

        def log_message(self, *args):
            pass

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HandlerFake)
    thread = _threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        porta = servidor.server_address[1]
        arm = modulo_store.ArmazenamentoUpstash(f"http://127.0.0.1:{porta}", "tok")

        _HandlerFake.contador = 0
        _HandlerFake.falhas = 0
        _HandlerFake.conexoes = set()
        for _ in range(3):
            assert arm._comando("SET", "k", "v") == {"result": "ok"}
            assert arm._pedido("GET", "get/k") == {"result": "ok"}
        assert len(_HandlerFake.conexoes) == 1, \
            "keep-alive deve reutilizar a mesma conexão entre chamadas"

        _HandlerFake.contador = 0
        _HandlerFake.falhas = 1
        _HandlerFake.conexoes = set()
        assert arm._comando("GET", "k") == {"result": "ok"}
        assert _HandlerFake.contador == 2, "5xx deve ser retentado uma vez"
    finally:
        servidor.shutdown()
        thread.join(timeout=5)
        servidor.server_close()
    _ok("transporte Upstash (keep-alive + retry)")


def teste_leitura_segura_falha_de_rede():
    """
    Fase 51: leitura do store com o servidor distribuído fora do ar não estoura
    o worker — os helpers de leitura devolvem None/[] (aborto silencioso) em vez
    de propagar OSError/http.client.HTTPException para a rota do OG ou handlers.
    """
    original = modulo_store.armazenamento
    import logging as _logging
    logger = _logging.getLogger("store")
    nivel_original = logger.level
    logger.setLevel(_logging.CRITICAL)
    try:
        modulo_store.armazenamento = modulo_store.ArmazenamentoUpstash(
            "http://127.0.0.1:1", "tok")
        assert modulo_store.carregar_sala("x") is None
        assert modulo_store.carregar_resumo("x") is None
        assert modulo_store.sala_do_sid("x") is None
        assert modulo_store.listar_resumos() == []
        assert modulo_store.listar_lobbys() == []
    finally:
        modulo_store.armazenamento = original
        logger.setLevel(nivel_original)
    _ok("leitura segura devolve None/[] em falha de rede (Fase 51)")


def teste_index_og_dinamico():
    """
    Fase 42 (N1): a home renderiza Open Graph dinâmico por sala para crawlers
    sem JS — com `?sala=<id>` válida (resumo existente), og:title cita a sala e
    og:description a ocupação; sem sala ou sala inexistente, cai no genérico.
    """
    _limpar()
    sala_og = "salaog1"
    modulo_store.salvar_resumo(sala_og, {
        'sala': sala_og, 'nome': 'Mesa do Zé', 'status': 'espera',
        'jogadores': 2, 'max_jogadores': 6, 'pode_entrar': True,
    })
    try:
        with app.test_client() as cliente:
            resposta = cliente.get(f"/?sala={sala_og}")
            html = resposta.get_data(as_text=True)
            assert "Mesa do Zé | Dadinho" in html, "og:title deve citar a sala"
            assert "2/6 jogador" in html, "og:description deve citar a ocupação"
            # Fase 44 (S6/S7): CSP em Report-Only por padrão, sem 'unsafe-inline'
            # no script-src (os onclick inline já foram migrados para data-acao).
            csp = resposta.headers.get("Content-Security-Policy-Report-Only") or ""
            diretivas = dict(part.strip().split(' ', 1) for part in csp.split(';')
                             if ' ' in part.strip())
            assert "script-src" in diretivas and "unsafe-inline" not in diretivas["script-src"], \
                "CSP Report-Only com script-src estrito (sem unsafe-inline)"

            html = cliente.get("/").get_data(as_text=True)
            assert "Dadinho — Jogo de Blefe de Dados" in html, \
                "sem sala deve cair no og genérico"

            html = cliente.get("/?sala=inexistente").get_data(as_text=True)
            assert "Dadinho — Jogo de Blefe de Dados" in html, \
                "sala inexistente deve cair no og genérico"
    finally:
        modulo_store.remover_resumo(sala_og)
        _limpar()
    _ok("OG dinâmico por sala (N1)")


def teste_mq_wiring():
    """
    Fase 25: o manager é opt-in por env DADINHO_MESSAGE_QUEUE. Com a env, o app
    usa GerenciadorRedisSeguro (canal "dadinho") e o boot não trava mesmo com URL
    inalcançável (a thread de listener re-tenta em background). Sem a env, o
    wiring mantém o GerenciadorThreadSeguro (regressão zero).
    """
    codigo = (
        "import os;"
        "os.environ['DADINHO_STORE']='memoria';"
        "os.environ['VERCEL']='1';"
        "os.environ['DADINHO_MESSAGE_QUEUE']='rediss://a:@fake:6379/0';"
        "import app;"
        "m=app.socketio.server.manager;"
        "assert type(m).__name__=='GerenciadorRedisSeguro', type(m).__name__;"
        "assert m.channel=='dadinho', m.channel;"
        "print('MQ_OK')"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ,
        capture_output=True, text=True, timeout=60,
    )
    _checar("message queue wiring (opt-in por env)",
            resultado.returncode == 0 and "MQ_OK" in resultado.stdout,
            (resultado.stderr or resultado.stdout).strip()[-500:])


def teste_redis_store_wiring():
    """
    Fase 46 (VPS): com DADINHO_REDIS_URL (Redis TCP local) e sem o Upstash, o
    store seleciona ArmazenamentoRedis e o lock distribuído não é no-op (usa o
    Redis local). Sem a env, regressão zero (cai no Upstash ou memória).
    """
    codigo = (
        "import os;"
        "os.environ['DADINHO_STORE']='';"
        "os.environ.pop('VERCEL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_URL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_TOKEN', None);"
        "os.environ['DADINHO_REDIS_URL']='redis://localhost:6379/0';"
        "import store;"
        "assert type(store.armazenamento).__name__=='ArmazenamentoRedis', type(store.armazenamento).__name__;"
        "print('REDIS_OK')"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ,
        capture_output=True, text=True, timeout=60,
    )
    _checar("store Redis TCP (VPS) selecionado por DADINHO_REDIS_URL",
            resultado.returncode == 0 and "REDIS_OK" in resultado.stdout,
            (resultado.stderr or resultado.stdout).strip()[-500:])


def teste_redis_lock_fake():
    """
    Fase 46: o lock distribuído também funciona sobre o ArmazenamentoRedis
    (SET NX/EX + DELEX IFEQ via script Lua). Usa um cliente Redis fake
    (redis-py duck-typed) para validar o tradutor `_comando` sem precisar de
    servidor Redis no CI.
    """
    import threading
    import time as _time

    class ClienteFake:
        """Mínimo de redis-py que o ArmazenamentoRedis usa (set/delete/get/script)."""

        def __init__(self):
            self._dados = {}
            self._trava = threading.Lock()

        def set(self, chave, valor, nx=False, ex=None, **kwargs):
            with self._trava:
                if nx and chave in self._dados:
                    return False
                self._dados[chave] = valor
            return True

        def get(self, chave):
            with self._trava:
                return self._dados.get(chave)

        def delete(self, *chaves):
            with self._trava:
                n = sum(1 for c in chaves if c in self._dados)
                for c in chaves:
                    self._dados.pop(c, None)
                return n

        def register_script(self, script):
            return lambda keys, args: self._delex(keys[0], args[0])

        def _delex(self, chave, token):
            with self._trava:
                if self._dados.get(chave) == token:
                    self._dados.pop(chave, None)
                    return 1
                return 0

    original = modulo_store.armazenamento
    tts, espera = modulo_store.TRAVA_TENTATIVAS, modulo_store.TRAVA_ESPERA_BASE
    modulo_store.TRAVA_TENTATIVAS = 2
    modulo_store.TRAVA_ESPERA_BASE = 0.01
    try:
        arm = modulo_store.ArmazenamentoRedis("redis://fake:6379/0")
        arm._redis = ClienteFake()
        arm._script_delex = arm._redis.register_script(modulo_store.ArmazenamentoRedis._LUA_DELEX)
        modulo_store.armazenamento = arm
        chave = modulo_store.PREFIXO_TRAVA + "s-redis"
        # Release com token errado é no-op (compare-and-del).
        assert arm._comando("SET", chave, "tokA", "NX", "EX", 120)["result"] == "OK"
        assert arm._comando("DELEX", chave, "IFEQ", "tokErrado")["result"] == 0
        assert arm._comando("GET", chave)["result"] == "tokA", \
            "token errado não pode apagar"
        assert arm._comando("DELEX", chave, "IFEQ", "tokA")["result"] == 1
        assert arm._comando("GET", chave)["result"] is None, \
            "release correto deve liberar"
        # Exclusão mútua via o context manager + contenda -> TravaIndisponivel.
        with modulo_store.trancar_sala_distribuida("s-redis"):
            try:
                with modulo_store.trancar_sala_distribuida("s-redis"):
                    raise AssertionError("segunda instância não pode adquirir lock ocupado")
            except modulo_store.TravaIndisponivel:
                pass
        with modulo_store.trancar_sala_distribuida("s-redis"):
            pass
        # Serialização round-trip no ArmazenamentoRedis (mesmo formato Upstash).
        import modelos
        lobby = modelos.Lobby(sala_id="s-redis", lobby_numero=7)
        jogador = modelos.Jogador(client_id="cli1")
        jogador.username = "Ana"
        lobby.adicionar_jogador(jogador)
        arm.salvar_sala(lobby)
        recarregado = arm.carregar_sala("s-redis")
        assert recarregado is not None and recarregado.jogadores[0].username == "Ana"
    finally:
        modulo_store.TRAVA_TENTATIVAS = tts
        modulo_store.TRAVA_ESPERA_BASE = espera
        modulo_store.armazenamento = original
    _ok("lock distribuído + round-trip sobre ArmazenamentoRedis (fake)")


def teste_resumo_dedup():
    class Espiao:
        def __init__(self):
            self.chamadas = 0

        def salvar_resumo(self, sala_id, resumo):
            self.chamadas += 1

        def remover_resumo(self, sala_id):
            pass

    original = modulo_store.armazenamento
    espiao = Espiao()
    modulo_store.armazenamento = espiao
    try:
        modulo_store._resumos_assinatura.clear()
        resumo = {"sala": "d", "nome": "Igual", "jogadores": 2}
        modulo_store.salvar_resumo("d", dict(resumo))
        modulo_store.salvar_resumo("d", dict(resumo))
        assert espiao.chamadas == 1, "resumo idêntico não pode ser reescrito"
        mudado = dict(resumo, jogadores=3)
        modulo_store.salvar_resumo("d", mudado)
        assert espiao.chamadas == 2, "resumo diferente deve ser gravado"
    finally:
        modulo_store.armazenamento = original
        modulo_store._resumos_assinatura.clear()
    _ok("dedup de resumo (economia de comandos)")


# --- Fase 28: robustez do store e dos locks ---------------------------------
def teste_h1_blob_corrompido():
    # Fase 28 (H1): blob inválido no Upstash não pode derrubar o handler com 500.
    arm = modulo_store.ArmazenamentoUpstash("http://fake", "tok")
    arm._pedido = lambda metodo, rota, corpo=None: {"result": "{bloco:corrompido!!"}
    assert arm.carregar_sala("corrompida") is None, "JSON inválido deve devolver None"
    # JSON válido mas que não desserializa numa árvore Lobby (mesmo efeito).
    arm._pedido = lambda metodo, rota, corpo=None: {"result": '{"partidas": 42}'}
    assert arm.carregar_sala("corrompida") is None, "árvore inválida deve devolver None"
    _ok("H1 (blob corrompido devolve None sem exceção)")


def teste_h1b_partida_vazia():
    # Fase 28 (H1b): Partida construída sem jogadores (blob corrompido que
    # referencia jogadores ausentes) não pode estourar IndexError/ZeroDivisionError.
    import modelos
    emit_salvo = _salvar_emit()
    _silenciar_emit()  # fora de request não há room/namespace
    try:
        lobby = modelos.Lobby(sala_id="vaz", lobby_numero=1)
        partida = modelos.Partida(do_lobby=lobby, jogadores=[], partida_numero=1, dados_qtd=2)
        assert partida.jogador_sorteado is None, \
            "partida sem jogadores não pode sortear (caminho secrets.choice)"
        # Com seed ativa (sem jogadores) também não pode zerar o módulo.
        com_seed = modelos.Partida(do_lobby=lobby, jogadores=[], partida_numero=2, dados_qtd=2,
                                   seed_info={"seed_final": "a" * 64})
        assert com_seed.jogador_sorteado is None, \
            "seed com partida vazia não pode estourar ZeroDivisionError"
        # Desserialização de um blob que referencia jogador ausente na mesa.
        dados = {
            "sala_id": "vaz", "versao": modelos.VERSAO_ATUAL, "jogadores": [],
            "espectadores": [], "partidas": [
                {"partida_num": 3, "dados_qtd": 2, "jogadores_ids": ["fantasma"]},
            ],
        }
        recarregado = modelos.Lobby.de_dict(dados)
        assert recarregado.partidas and recarregado.partidas[0].jogador_sorteado is None
    finally:
        _restaurar_emit(emit_salvo)
    _ok("H1b (Partida sem jogadores sem IndexError)")


def teste_h4_lock_nao_reconfigura_na_secao_critica():
    # Fase 28 (H4): `esquecer_sala` chamado DENTRO da seção crítica não pode
    # liberar o registro da trava — o request seguinte continuaria mutando o
    # mesmo Lobby com um RLock novo. A remoção é adiada para o último holder.
    import threading as _threading
    sala = "h4"
    with modulo_store._travas_guard:
        modulo_store._travas_salas.pop(sala, None)
    ordem = []

    def _secao_a():
        with modulo_store.trancar_sala(sala):
            ordem.append("A-dentro")
            # GC dentro da seção crítica (sala esvaziou): esquecer_sala roda
            # enquanto A ainda está no `with trancar_sala`.
            modulo_store.esquecer_sala(sala)
            time.sleep(0.3)
            ordem.append("A-sai")

    def _secao_b():
        time.sleep(0.05)
        with modulo_store.trancar_sala(sala):
            ordem.append("B-dentro")
        ordem.append("B-sai")

    ta = _threading.Thread(target=_secao_a)
    tb = _threading.Thread(target=_secao_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    assert ordem == ["A-dentro", "A-sai", "B-dentro", "B-sai"], \
        f"B não pode adquirir lock distinto antes de A sair: {ordem}"
    with modulo_store._travas_guard:
        assert sala not in modulo_store._travas_salas, \
            "trava deve ser esquecida após o último holder soltar"
    _ok("H4 (lock não é reconfigurado dentro da seção crítica)")


# --- Fase 29: regras de jogo (aposta irrespondível e cap do placeholder) -----
def teste_h2_aposta_irrespondivel_clampeada():
    # Fase 29 (H2): aposta acima do total teórico de dados da mesa é impossível
    # de responder (o desafiado não consegue subir) — o servidor clampeia no
    # máximo em vez de aceitar uma jogada que trava o turno.
    _limpar()
    clis, lobby = _conectar_trio(1)  # 3 jogadores, 1 dado cada = 3 dados na mesa
    partida = lobby.partidas[-1]
    rodada = partida.rodadas[-1]
    vez = rodada.vez_atual
    total = sum(j.dados_qtd for j in partida.jogadores)
    assert total == 3
    cli_vez, chave_vez = clis[vez.username]
    cli_vez.emit("apostar", {"dados": {"chave": chave_vez, "dado": 6, "quantidade": 100}})
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 1, "aposta clampeada deve ser aceita (turno criado)"
    assert rodada.turnos[0].dado_qtd == total, \
        f"quantidade deve ser clampeada no total: {rodada.turnos[0].dado_qtd} != {total}"
    assert rodada.turnos[0].dado_face == 6, "a face da aposta deve ser preservada"

    # Aposta no máximo não pode subir — o próximo é forçado a desconfiar e a
    # conferência fecha normalmente (o fluxo não trava).
    proximo = rodada.vez_atual
    assert proximo is not vez, "a vez deve ter avançado para o próximo"
    clis[proximo.username][0].emit(
        "desconfiar", {"dados": {"chave": clis[proximo.username][1]}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 3, f"conferência deve fechar após desconfiar, página={lobby.pagina}"
    _desconectar_todos(clis)
    _limpar()
    _ok("H2 (aposta acima do total é clampeada no máximo)")


def teste_h3_cap_placeholder_nao_burla_limite():
    # Fase 29 (H3): `tem_chave=1` é só um sinal booleano — não pode burlar o
    # limite da sala. O cap vale para o placeholder também.
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"max_jogadores": 3}})
    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c3, cs3, _ = _conectar()
    c3.emit("apelido", {"apelido_msg": "Caio"})
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.jogadores) == 3, "pré-condição: sala de espera cheia (3/3)"

    c4 = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    eventos = c4.get_received()
    assert _achar_evento(eventos, "sala_cheia") is not None, \
        "tem_chave=1 não pode criar placeholder em sala de espera cheia"
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.jogadores) == 3, "placeholder não pode estourar max_jogadores"
    assert not lobby.espectadores, "placeholder não pode vazar para espectadores na espera"
    c4.disconnect()
    _desconectar_todos({"Ana": (c1, cs1), "Bia": (c2, cs2), "Caio": (c3, cs3)})
    _limpar()

    # Partida em andamento: MAX_ESPECTADORES também vale para tem_chave=1.
    clis, lobby = _conectar_trio(1)
    limite = modulo_app.MAX_ESPECTADORES
    extras = []
    for _ in range(limite):
        c = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
        c.get_received()
        extras.append(c)
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.espectadores) == limite, \
        f"placeholders até o cap: {len(lobby.espectadores)} != {limite}"
    c_extra = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    eventos = c_extra.get_received()
    assert _achar_evento(eventos, "sala_cheia") is not None, \
        "espectador acima de MAX_ESPECTADORES deve levar sala_cheia"
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.espectadores) == limite, "não pode estourar MAX_ESPECTADORES"
    c_extra.disconnect()
    for c in extras:
        c.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("H3 (cap vale para o placeholder com tem_chave=1)")


# --- Expulsão de jogador (Fase 19) -----------------------------------------
def teste_expulsar_bot():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 2})
    lobby = modulo_store.carregar_sala(SALA)
    bots = [j for j in lobby.jogadores if j.is_ia]
    assert len(bots) == 2, "pré-condição: dois bots na sala"
    c1.emit("expulsar_jogador", {"chave": cs1["chave_secreta"], "client_id": bots[0].client_id})
    lobby = modulo_store.carregar_sala(SALA)
    assert not any(j.client_id == bots[0].client_id for j in lobby.jogadores), \
        "bot expulso deve sair do lobby"
    assert len([j for j in lobby.jogadores if j.is_ia]) == 1, "só o bot expulso deve sair"
    assert lobby.retornar_master() is not False, "master humano continua master"
    c1.disconnect()
    _limpar()
    _ok("expulsar IA (Fase 19)")


def teste_expulsar_humano():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    bia = next(j for j in lobby.jogadores if j.username == "Bia")
    assert ana.master and not bia.master

    # Não-master não pode expulsar.
    c2.emit("expulsar_jogador", {"chave": cs2["chave_secreta"], "client_id": ana.client_id})
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.jogadores) == 2, "não-master não pode expulsar"
    # Master não pode se auto-expulsar.
    c1.emit("expulsar_jogador", {"chave": cs1["chave_secreta"], "client_id": ana.client_id})
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.jogadores) == 2, "master não pode se auto-expulsar"

    c1.emit("expulsar_jogador", {"chave": cs1["chave_secreta"], "client_id": bia.client_id})
    lobby = modulo_store.carregar_sala(SALA)
    assert not any(j.client_id == bia.client_id for j in lobby.jogadores), \
        "expulso deve sair do lobby"
    assert funcoes_gerais.sala_do_cliente(bia.client_id) is None, \
        "índice sid do expulso deve ser limpo"
    eventos_expulso = c2.get_received()
    assert _achar_evento(eventos_expulso, "expulso_da_sala") is not None, \
        "expulso deve receber expulso_da_sala"
    assert _achar_evento(eventos_expulso, "jogador_expulso") is None, \
        "expulso não deve receber os eventos da room após sair"
    eventos_room = c1.get_received()
    assert _achar_evento(eventos_room, "jogador_expulso") is not None, \
        "a room deve saber quem foi expulso"
    assert lobby.jogadores[0].master, "o master continua na sala"
    c1.disconnect()
    _limpar()
    _ok("expulsar humano (Fase 19)")


def teste_expulsar_durante_partida():
    _limpar()
    clis, lobby = _conectar_trio(2)
    partida = lobby.partidas[-1]
    alvo = next(j for j in partida.jogadores if j.username != "Ana")
    ana_cli, ana_chave = clis["Ana"]
    ana_cli.emit("expulsar_jogador", {"chave": ana_chave, "client_id": alvo.client_id})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    rodada = partida.rodadas[-1]
    assert alvo.client_id not in [j.client_id for j in partida.jogadores], \
        "expulso deve sair da partida"
    assert alvo.client_id not in [j.client_id for j in lobby.jogadores], \
        "expulso deve sair do lobby"
    assert alvo.client_id not in [j.client_id for j in rodada.jogadores], \
        "expulso deve sair da rodada (senão a conferência espera um fantasma)"
    assert lobby.pagina == 2, "partida não pode travar após a expulsão"
    assert rodada.vez_atual is not alvo, "vez não pode ficar no expulso"
    _desconectar_todos(clis)
    _limpar()
    _ok("expulsar durante a partida (Fase 19)")


# --- Jogada automática por tempo máximo (Fase 21) ---------------------------
def teste_autojogar():
    from datetime import datetime, timedelta

    def _envelhecer(rodada, campo, segundos):
        setattr(rodada, campo, datetime.now() - timedelta(seconds=segundos))

    def _iniciar(tempo):
        c1, cs1, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2, cs2, _ = _conectar()
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                       "config": {"tempo_max_jogada": tempo}})
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 1, f"deve estar na rolagem, pagina={lobby.pagina}"
        # Os payloads da rolagem e do turno anunciado devem trazer o tempo máximo.
        ev1 = c1.get_received()
        ev2 = c2.get_received()
        constr = [e for e in ev1 if e["name"] == "construtor_dados"]
        assert constr and constr[-1]["args"][0].get("tempo_max") == tempo, \
            "construtor_dados deve trazer tempo_max"
        mt = ([e for e in ev1 if e["name"] == "meu_turno"]
              or [e for e in ev2 if e["name"] == "meu_turno"])
        assert mt and mt[-1]["args"][0].get("tempo_max") == tempo, \
            "meu_turno deve trazer tempo_max"
        return c1, cs1["chave_secreta"], c2, cs2["chave_secreta"]

    _limpar()
    c1, k1, c2, k2 = _iniciar(30)
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]

    # Autojogar imediato (tempo não passou) é ignorado.
    c1.emit("autojogar", {"chave": k1})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.joguei_dados is False, "auto-roll instantâneo não pode valer"

    # Envelhece a rolagem: o autojogar rola os dados do atrasado.
    _envelhecer(rodada, "inicio_rolagem_em", 999)
    modulo_store.salvar_sala(lobby)
    c1.emit("autojogar", {"chave": k1})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.joguei_dados is True, "autojogar deve rolar os dados de Ana"
    assert _achar_evento(c1.get_received(), "jogar_dados_resultado") is not None, \
        "auto-roll deve emitir o resultado dos dados"
    assert lobby.pagina == 1, "Bia ainda não rolou, deve seguir na rolagem"

    # Bia também atrasa: o autojogar dela destrava a página 2.
    c2.emit("autojogar", {"chave": k2})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2, f"todos rolados deve ir para os turnos, pagina={lobby.pagina}"
    rodada = lobby.partidas[-1].rodadas[-1]
    vez = rodada.vez_atual
    vez_cli = c1 if vez.username == "Ana" else c2
    outro = c2 if vez.username == "Ana" else c1
    chave_vez = k1 if vez.username == "Ana" else k2

    # Autojogar imediato no turno é ignorado (tempo não passou).
    vez_cli.emit("autojogar", {"chave": chave_vez})
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 0, "auto-aposta instantânea não pode valer"

    # Jogador fora da vez é ignorado mesmo com tempo passado.
    _envelhecer(rodada, "vez_em", 999)
    modulo_store.salvar_sala(lobby)
    outro.emit("autojogar", {"chave": k1 if vez.username == "Bia" else k2})
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 0, "quem não é o da vez não pode auto-jogar"

    # Da vez, com tempo passado: auto-aposta válida e a vez avança.
    vez_cli.emit("autojogar", {"chave": chave_vez})
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 1, "auto-aposta deve criar um turno válido"
    assert rodada.vez_atual is not vez, "a vez deve avançar após o auto-jogo"

    # Config tempo=0 (desligado): autojogar é no-op mesmo com tempo passado.
    c1.disconnect()
    c2.disconnect()
    _limpar()
    c1, k1, c2, k2 = _iniciar(0)
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    _envelhecer(rodada, "inicio_rolagem_em", 999)
    modulo_store.salvar_sala(lobby)
    c1.emit("autojogar", {"chave": k1})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.joguei_dados is False, "com tempo desligado o autojogar é no-op"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("jogada automática por tempo máximo (Fase 21)")


def teste_retomar_identidade_por_evento():
    """
    Fase D: a `chave_secreta` não trafega mais na query string do handshake.
    No connect o servidor cria um "placeholder"; a identidade é retomada pela
    primeira mensagem (`retomar_identidade`), trocando o placeholder pela
    identidade real (jogador em janela de reconexão) sem duplicar nem perder o
    estado.
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2, cs2, _ = _conectar()
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    ana_chave = ana.chave_secreta
    ana_sid = ana.client_id

    # Ana cai no meio da partida: entra na janela de reconexão (Bia ativa).
    c1.disconnect()
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.desconectado_em is not None and ana.client_id == ana_sid

    # Reconnect sem chave na query (só o sinal booleano tem_chave): o servidor
    # cria um placeholder (espectador transitório, a partida está em andamento).
    c1b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.espectadores) == 1, "placeholder deve ser espectador transitório"
    sid_novo = lobby.espectadores[0].client_id

    # Primeira mensagem: retoma a identidade pela chave guardada no cliente.
    c1b.emit("retomar_identidade", {"chave": ana_chave})
    lobby = modulo_store.carregar_sala(SALA)
    anas = [j for j in lobby.jogadores if j.username == "Ana"]
    assert len(anas) == 1, "não pode duplicar o jogador retomado"
    assert anas[0].client_id == sid_novo, "sid novo deve ser religado à identidade"
    assert anas[0].desconectado_em is None, "retomada deve encerrar a janela de graça"
    assert not lobby.espectadores, "placeholder deve sair dos espectadores"
    assert anas[0].chave_secreta == ana_chave, "a chave da identidade deve ser mantida"

    eventos = c1b.get_received()
    retomado = [e for e in eventos if e["name"] == "connect_start"]
    assert retomado and retomado[-1]["args"][0].get("username") == "Ana", \
        "servidor deve reemitir connect_start com a identidade retomada"
    assert _achar_evento(eventos, "construtor_dados") is not None, \
        "snapshot da identidade retomada deve ser enviado (página 1)"

    c1b.disconnect()
    c2.disconnect()
    _limpar()
    _ok("retomar identidade por evento (Fase D)")


def teste_retomar_negado_chave_stale():
    """
    Fase D: um cliente com chave de OUTRA sala (stale no sessionStorage) conecta
    com tem_chave=1; a retomada falha e o servidor avisa `retomar_negado` para o
    front adotar a chave do placeholder (senão a chave antiga ficaria para sempre).
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2 = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    chave_stale = "a" * 32
    c2.emit("retomar_identidade", {"chave": chave_stale})
    eventos = c2.get_received()
    negado = [e for e in eventos if e["name"] == "retomar_negado"]
    assert negado, "chave que não pertence à sala deve responder retomar_negado"
    # Fase 30: chave stale (sessão de outra sala) tem o motivo próprio.
    motivo = negado[-1]["args"][0].get("motivo", {})
    assert motivo.get("chave") == "msg.retomar_outra_sala", \
        f"chave stale deve ter motivo outra_sala, veio {motivo}"
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.jogadores) == 2, "placeholder segue como jogador novo"
    c2.disconnect()
    c1.disconnect()
    _limpar()
    _ok("retomar_negado (chave stale)")


def teste_refresh_conferencia_preserva_ok():
    """
    Fase D2: após um refresh NA CONFERÊNCIA (página 3), o placeholder não pode
    piscar como ESPECTADOR antes do snapshot real — o `espectador` escondia o
    botão "Ok" (`bot_confe_fim`) e o snapshot da retomada nunca o reexibia,
    travando a rodada em "Aguardando você...". Com a retomada adiada, o
    snapshot sai só na retomada da identidade (sem `espectador` em momento
    algum).
    """
    _limpar()
    clis, lobby = _conectar_trio(1)
    _rodada_ate_conferencia(clis)
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 3, f"deve estar na conferência, página={lobby.pagina}"
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    ana_chave = ana.chave_secreta
    ana_sid = ana.client_id

    clis["Ana"][0].disconnect()
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.desconectado_em is not None and ana.client_id == ana_sid

    # Refresh: conecta com tem_chave=1; o snapshot do placeholder é ADIADO.
    c = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    lobby = modulo_store.carregar_sala(SALA)
    sid_novo = next(j.client_id for j in lobby.espectadores)
    presentes = c.get_received()
    assert _achar_evento(presentes, "connect_start") is not None, \
        "placeholder deve receber connect_start"
    assert _achar_evento(presentes, "espectador") is None, \
        "snapshot do placeholder não pode piscar como espectador (gesto do bug)"

    c.emit("retomar_identidade", {"chave": ana_chave})
    eventos = c.get_received()
    assert _achar_evento(eventos, "espectador") is None, \
        "snapshot da retomada não pode conter espectador (esconderia o botão Ok)"
    assert _achar_evento(eventos, "cards_conferencia") is not None, \
        "snapshot da retomada deve reconstruir a conferência (página 3)"

    lobby = modulo_store.carregar_sala(SALA)
    anas = [j for j in lobby.jogadores if j.username == "Ana"]
    assert len(anas) == 1 and anas[0].client_id == sid_novo, \
        "retomada deve religar o sid novo à identidade de Ana"

    c.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("refresh na conferência preserva o botão Ok (Fase D2)")


def teste_heartbeat_resincroniza_vez_partida():
    """
    Fase D2: um jogador na página de turnos (2) que perdeu o dispatcher de vez
    (gap entre instâncias logo após um refresh) informa `vez=''` no heartbeat;
    o servidor detecta a divergência, lê o estado fresco e reemite o
    `meu_turno`/`espera_turno` — sem isso ele ficaria sem o menu de jogada.
    """
    _limpar()
    clis, lobby = _conectar_trio(1)
    rodada = lobby.partidas[-1].rodadas[-1]
    vez = rodada.vez_atual

    outro = next(nome for nome in clis if nome != vez.username)
    c_outro, chave_outro = clis[outro]
    c_outro.get_received()
    c_outro.emit("heartbeat", {"chave": chave_outro, "pagina": 2, "vez": ""})
    eventos = c_outro.get_received()
    espera = _achar_evento(eventos, "espera_turno")
    assert espera is not None and espera.get("username") == vez.username, \
        "heartbeat deve reemitir espera_turno com o da vez atual"
    assert _achar_evento(eventos, "meu_turno") is None, \
        "jogador fora da vez não pode receber meu_turno"

    c_vez, chave_vez = clis[vez.username]
    c_vez.get_received()
    c_vez.emit("heartbeat", {"chave": chave_vez, "pagina": 2, "vez": ""})
    eventos = c_vez.get_received()
    mt = _achar_evento(eventos, "meu_turno")
    assert mt is not None and mt.get("username") == vez.username, \
        "heartbeat deve reemitir meu_turno para o próprio da vez"

    _desconectar_todos(clis)
    _limpar()
    _ok("heartbeat re-sincroniza a vez da partida (Fase D2)")


def teste_ultimo_humano_sala_de_ias_ganha_grace():
    """
    Fase 23: o último humano de uma partida só com IAs ganha a janela de
    reconexão mesmo sem outro humano ativo. Antes, o disconnect o removia na
    hora e apagava a sala junto — um blip (tab em segundo plano, reciclagem da
    função na Vercel) perdia a partida inteira. Com a graça, o jogador volta via
    `retomar_identidade` e a partida segue.
    """
    _limpar()
    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 60
    try:
        c1, cs1, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 1
        ana_chave = next(j.chave_secreta for j in lobby.jogadores if j.username == "Ana")
        ana_sid = next(j.client_id for j in lobby.jogadores if j.username == "Ana")

        # Queda do único humano no meio da partida (só o bot sobra).
        c1.disconnect()
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby is not None, "a sala não pode ser apagada na hora (Fase 23)"
        ana = next(j for j in lobby.jogadores if j.username == "Ana")
        assert ana.desconectado_em is not None, "o último humano deve entrar na janela de graça"
        assert ana.client_id == ana_sid

        # Volta dentro da janela: retoma a identidade e a partida segue.
        c1b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
        c1b.emit("retomar_identidade", {"chave": ana_chave})
        lobby = modulo_store.carregar_sala(SALA)
        anas = [j for j in lobby.jogadores if j.username == "Ana"]
        assert len(anas) == 1, "não pode duplicar o jogador retomado"
        assert anas[0].desconectado_em is None, "retomada deve encerrar a janela de graça"
        assert anas[0].client_id != ana_sid, "o sid novo deve ser religado à identidade"
        assert lobby.pagina == 1, "a partida em andamento deve ser preservada"
        assert any(j.is_ia for j in lobby.jogadores), "o bot da partida deve seguir na mesa"
        c1b.disconnect()
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original
        _limpar()
    _ok("último humano de sala só de IAs ganha a janela de reconexão (Fase 23)")


def teste_volta_apos_substituicao_ia():
    """
    Fase 30: caiu no meio da partida com a substituição ligada -> a graça expira
    e a IA joga no lugar -> o humano volta e retoma o controle (`is_ia` volta a
    False sem duplicar). Cobre o ramo `era_bot_nativo`/`is_ia=False` da
    `retomar_identidade`.
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"substituir_desconectado_por_ia": True}})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    ana_chave = ana.chave_secreta
    ana_sid = ana.client_id

    # Ana cai e a graça expira: vira IA (Bia está ativa). A partida segue.
    c1.disconnect()
    c2.emit("verificar_desconectados")  # grace = 0 no teste
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.is_ia, "caído com a opção ligada deve virar IA"
    assert ana.client_id == ana_sid, "substituído mantém sid e chave"

    # Ana volta (sid novo): a retomada devolve o controle na mesma partida.
    c1b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    c1b.emit("retomar_identidade", {"chave": ana_chave})
    lobby = modulo_store.carregar_sala(SALA)
    anas = [j for j in lobby.jogadores if j.username == "Ana"]
    assert len(anas) == 1, "retomada não pode duplicar o jogador"
    assert anas[0].is_ia is False, "retomada deve devolver o controle ao humano"
    assert anas[0].ia_nivel is None, "nível de IA deve ser limpo na retomada"
    assert anas[0].desconectado_em is None, "retomada deve encerrar a janela"
    assert anas[0].partida_atual is lobby.partidas[-1], "a partida segue com Ana"
    eventos = c1b.get_received()
    assert _achar_evento(eventos, "construtor_dados") is not None, \
        "snapshot da identidade retomada deve ser enviado"
    c1b.disconnect()
    c2.disconnect()
    _limpar()
    _ok("volta após substituição por IA devolve o controle (Fase 30)")


def teste_grace_espera_preserva_identidade():
    """
    Fase 30: quem cai na ESPERA ganha a janela de reconexão e, ao voltar,
    mantém apelido e prontidão (antes um blip de conexão removia o jogador na
    hora e ele voltava como identidade nova, sem nada).
    """
    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 30
    try:
        _limpar()
        c1, cs1, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c1.emit("ficar_pronto", {"chave": cs1["chave_secreta"]})
        c1.get_received()  # descarta os eventos do apelido/pronto
        ana_chave = cs1["chave_secreta"]

        c1.disconnect()  # caiu na espera: entra na graça, não é removido
        lobby = modulo_store.carregar_sala(SALA)
        ana = next(j for j in lobby.jogadores if j.username == "Ana")
        assert ana.desconectado_em is not None, "queda na espera deve ganhar a janela"
        assert ana.pronto, "prontidão preservada durante a graça"

        # Volta com sid novo: retoma a identidade (apelido/pronto intactos).
        c1b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
        c1b.emit("retomar_identidade", {"chave": ana_chave})
        lobby = modulo_store.carregar_sala(SALA)
        anas = [j for j in lobby.jogadores if j.username == "Ana"]
        assert len(anas) == 1, "retomada não pode duplicar"
        assert anas[0].desconectado_em is None, "retomada deve encerrar a janela"
        assert anas[0].pronto, "prontidão preservada na retomada"
        assert anas[0].master, "master não pode ser perdido na retomada"
        c1b.disconnect()
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original
        _limpar()
    _ok("queda na espera ganha graça e preserva identidade (Fase 30)")


def teste_retomar_negado_vaga_perdida():
    """
    Fase 30: vaga expirada por inatividade tem motivo próprio no `retomar_negado`
    (diferente da chave stale de outra sala).
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    ana_chave = ana.chave_secreta

    # Ana cai e a graça expira SEM a opção de IA: é removida (vaga registrada).
    c1.disconnect()
    c2.emit("verificar_desconectados")  # grace = 0 no teste
    lobby = modulo_store.carregar_sala(SALA)
    assert all(j.username != "Ana" for j in lobby.jogadores), "Ana deve sair da sala"
    assert ana_chave in lobby.vagas_recentes, "remoção deve registrar a vaga"

    # Ana volta: retomar_negado com o motivo de vaga perdida.
    c1b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
    c1b.emit("retomar_identidade", {"chave": ana_chave})
    eventos = c1b.get_received()
    negado = [e for e in eventos if e["name"] == "retomar_negado"]
    assert negado, "deve receber retomar_negado"
    motivo = negado[-1]["args"][0].get("motivo", {})
    assert motivo.get("chave") == "msg.vaga_perdida_inatividade", \
        f"vaga expirada deve ter motivo vaga_perdida_inatividade, veio {motivo}"
    c1b.disconnect()
    c2.disconnect()
    _limpar()
    _ok("retomar_negado com motivo de vaga perdida (Fase 30)")


def teste_iniciar_sem_fantasma():
    """
    Fase 30: quem caiu na ESPERA (dentro da graça) não entra na mesa como
    fantasma quando o master inicia — vira IA (opção ligada) e, ao voltar,
    retoma o controle. Sem a opção, é removido antes do início.
    """
    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 30
    try:
        # Com a opção ligada: o caído vira IA na partida.
        _limpar()
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                       "config": {"substituir_desconectado_por_ia": True}})
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        c2.disconnect()  # Bia cai na espera, ainda dentro da graça
        lobby = modulo_store.carregar_sala(SALA)
        bia = next(j for j in lobby.jogadores if j.username == "Bia")
        assert bia.desconectado_em is not None, "queda na espera entra na graça"

        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        bia = next(j for j in lobby.jogadores if j.username == "Bia")
        assert bia.is_ia, "caído da espera com opção ligada vira IA na partida"
        assert bia.partida_atual is lobby.partidas[-1], "IA deve entrar na mesa"
        assert lobby.pagina == 1

        # Bia volta: retoma o controle na partida.
        c2b = socketio.test_client(app, query_string=f"sala={SALA}&tem_chave=1")
        c2b.emit("retomar_identidade", {"chave": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(SALA)
        bias = [j for j in lobby.jogadores if j.username == "Bia"]
        assert len(bias) == 1 and not bias[0].is_ia, "retomada devolve o controle"
        c2b.disconnect()
        c1.disconnect()

        # Sem a opção: o caído da espera é removido e a partida segue sem ele.
        _limpar()
        c3, cs3, _ = _conectar()
        c4, cs4, _ = _conectar()
        c3.emit("apelido", {"apelido_msg": "Ana"})
        c4.emit("apelido", {"apelido_msg": "Bia"})
        c3.emit("adicionar_ia", {"chave": cs3["chave_secreta"], "nivel": 2, "quantidade": 1})
        c4.emit("ficar_pronto", {"chave": cs4["chave_secreta"]})
        c4.disconnect()
        c3.emit("iniciar_partida", {"chave": cs3["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert all(j.username != "Bia" for j in lobby.jogadores), \
            "sem a opção, o caído da espera deve sair da mesa"
        assert lobby.pagina == 1, "a partida segue sem o caído (master + bot)"
        c3.disconnect()
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original
        _limpar()
    _ok("início sem fantasma: caído da espera vira IA ou sai (Fase 30)")


def teste_iniciar_repetido_nao_toca_grace():
    """
    Fase 30: um `iniciar_partida` repetido com a sala já em `jogando` (clique
    duplo, segundo tab) não pode converter/remover quem está na janela de graça.
    """
    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 30
    try:
        _limpar()
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                       "config": {"substituir_desconectado_por_ia": True}})
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.status == "jogando"

        # Bia cai na partida (em graça) e o master re-emite iniciar_partida.
        c2.disconnect()
        lobby = modulo_store.carregar_sala(SALA)
        bia = next(j for j in lobby.jogadores if j.username == "Bia")
        assert bia.desconectado_em is not None, "pré-condição: Bia em graça"
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        bia = next(j for j in lobby.jogadores if j.username == "Bia")
        assert bia is not None, "iniciar repetido não pode remover quem está em graça"
        assert not bia.is_ia, "iniciar repetido não pode converter a graça em IA"
        assert bia.desconectado_em is not None, "a janela de graça segue valendo"
        c1.disconnect()
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original
        _limpar()
    _ok("iniciar repetido com a sala jogando não toca a graça (Fase 30)")


def teste_apelido_editavel_ate_pronto():
    """
    Fase 31: o apelido pode ser trocado quantas vezes quiser na espera (sem
    colidir consigo mesmo), mas fica travado a partir do "ficar pronto".
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    # Reenviar o próprio apelido não vira "Ana_1" (exclui a si da unicidade).
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("apelido", {"apelido_msg": "AnaNova"})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if not j.is_ia and j.username.startswith("Ana"))
    assert ana.username == "AnaNova", \
        f"apelido deve ser trocado livremente na espera, veio {ana.username}"
    # Apelido que já existe na sala ganha sufixo numérico.
    c2.emit("apelido", {"apelido_msg": "AnaNova"})
    lobby = modulo_store.carregar_sala(SALA)
    assert any(j.username == "AnaNova_1" for j in lobby.jogadores), \
        "apelido duplicado ganha sufixo numérico"
    # Pronto: o apelido não muda mais.
    c1.emit("ficar_pronto", {"chave": cs1["chave_secreta"]})
    c1.emit("apelido", {"apelido_msg": "NaoPode"})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "AnaNova")
    assert ana.username == "AnaNova", "apelido travado depois de ficar pronto"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("apelido editável na espera e travado ao ficar pronto")


def teste_iniciar_caido_sem_apelido_removido():
    """
    Fase 30: quem caiu na espera SEM apelido é removido no início (não vira bot
    sem nome — um bot sem nome travaria `pode_iniciar` em `sem_apelido`).
    """
    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 30
    try:
        _limpar()
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()  # não define apelido
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                       "config": {"substituir_desconectado_por_ia": True}})
        c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
        c2.disconnect()  # caiu na espera sem apelido, em graça
        lobby = modulo_store.carregar_sala(SALA)
        caiu = next(j for j in lobby.jogadores
                    if not j.is_ia and not j.master and j.desconectado_em is not None)
        assert caiu is not None, "pré-condição: caído sem apelido na graça"

        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 1, "partida inicia com master + bot"
        assert all(j.username for j in lobby.jogadores), \
            "não pode sobrar bot sem nome na mesa"
        c1.disconnect()
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original
        _limpar()
    _ok("caído sem apelido na espera é removido (não vira bot sem nome)")


def teste_sair_da_sala_espectador():
    """
    Fase 30: o espectador pode sair da sala e voltar ao menu — o servidor o
    remove (lobby, índice sid) e a partida segue. Jogador ativo não sai via
    `sair_da_sala` (segue usando a janela de reconexão).
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    c3, _, ev3 = _conectar()  # entra no meio: espectador
    assert _achar_evento(ev3, "espectador") is not None
    lobby = modulo_store.carregar_sala(SALA)
    esp = next(e for e in lobby.espectadores)
    esp_sid = esp.client_id
    assert funcoes_gerais.sala_do_cliente(esp_sid) == SALA

    # Jogador ativo tentando sair: no-op (não é espectador).
    c2.emit("sair_da_sala", {"chave": cs2["chave_secreta"]})
    lobby = modulo_store.carregar_sala(SALA)
    assert len(lobby.espectadores) == 1, "jogador ativo não pode sair via sair_da_sala"

    # Espectador sai (sem precisar de chave: a identidade é o sid).
    c3.emit("sair_da_sala", {"chave": ""})
    eventos = c3.get_received()
    assert _achar_evento(eventos, "saiu_da_sala") is not None, "deve confirmar a saída"
    lobby = modulo_store.carregar_sala(SALA)
    assert not lobby.espectadores, "espectador deve sair do lobby"
    assert funcoes_gerais.sala_do_cliente(esp_sid) is None, "índice sid deve ser limpo"
    assert lobby.status == "jogando" and lobby.pagina == 1, "a partida segue"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("espectador sai da sala e a partida segue (Fase 30)")


def teste_sair_da_sala_lobby():
    """
    Fase 30: jogador na ESPERA pode sair explicitamente (sem consumir a janela
    de reconexão) — exige a chave secreta. Se o master sai, a outra pessoa é
    reeleita; se era o último humano, o GC fecha a sala. Jogador ativo no meio
    da partida continua sendo no-op (coberto em `teste_sair_da_sala_espectador`).
    """
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})

    # Chave errada: no-op (invariante: mutação exige a chave secreta do jogador).
    c1.emit("sair_da_sala", {"chave": "errada"})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.buscar_jogador_pela_chave(cs1["chave_secreta"]) is not None, \
        "chave errada não pode remover ninguém"

    # Master sai com a chave certa: é removido e o outro vira master.
    lobby = modulo_store.carregar_sala(SALA)
    sid1 = lobby.buscar_jogador_pela_chave(cs1["chave_secreta"]).client_id
    c1.emit("sair_da_sala", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    assert _achar_evento(eventos, "saiu_da_sala") is not None, "deve confirmar a saída"
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.buscar_jogador_pela_chave(cs1["chave_secreta"]) is None, \
        "master que saiu deve ser removido do lobby"
    resto = lobby.retornar_master()
    assert resto is not None and not resto.is_ia and resto.username == "Bia", \
        "master deve ser repassado a outro humano"
    assert funcoes_gerais.sala_do_cliente(sid1) is None, \
        "índice sid do que saiu deve ser limpo"
    assert cs1["chave_secreta"] not in lobby.vagas_recentes, \
        "saída explícita não pode acusar 'vaga perdida por inatividade'"
    sid2 = lobby.buscar_jogador_pela_chave(cs2["chave_secreta"]).client_id
    assert funcoes_gerais.sala_do_cliente(sid2) == SALA, \
        "índice sid de quem restou continua apontando para a sala"

    # Último humano sai: sala é fechada.
    c2.emit("sair_da_sala", {"chave": cs2["chave_secreta"]})
    assert modulo_store.carregar_sala(SALA) is None, "último humano saindo fecha a sala"
    assert funcoes_gerais.sala_do_cliente(sid2) is None, \
        "índice sid do último a sair deve ser limpo"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("jogador e master saem do lobby explicitamente (Fase 30)")


def teste_sair_da_sala_eliminado():
    """
    Fase 30: quem zerou os dados (vira espectador na tela mas segue no lobby)
    pode sair explicitamente — `partida_atual` continua apontando para a
    partida, mas o jogador não está mais nela. Jogador ativo segue no-op.
    """
    _limpar()
    clis, lobby = _conectar_trio(1)

    # Simula a eliminação (modelos.py:1164-1173): saiu da partida, zerou os
    # dados e o rodada_atual, mas `partida_atual` fica apontando para a partida.
    partida = lobby.partidas[-1]
    alvo = next(j for j in partida.jogadores if j.username != "Ana")
    nome_alvo = alvo.username
    alvo.joguei_dados = False
    alvo.rodadas = []
    alvo.turnos = []
    alvo.rodada_atual = None
    alvo.turno_atual = None
    alvo.dados_qtd = 0
    partida.jogadores.remove(alvo)
    lobby.marcar_visto()
    modulo_store.salvar_sala(lobby)

    # Eliminado sai: `saiu_da_sala` e removido do lobby; a partida segue.
    c_alvo, chave_alvo = clis[nome_alvo]
    c_alvo.emit("sair_da_sala", {"chave": chave_alvo})
    assert _achar_evento(c_alvo.get_received(), "saiu_da_sala") is not None, \
        "eliminado deve confirmar a saída"
    lobby = modulo_store.carregar_sala(SALA)
    assert all(j.username != nome_alvo for j in lobby.jogadores), \
        "eliminado que saiu deve ser removido do lobby"
    assert chave_alvo not in lobby.vagas_recentes, \
        "saída explícita não pode acusar 'vaga perdida por inatividade'"
    assert lobby.pagina == 2, "a partida segue para os demais"

    # Jogador ativo (ainda na partida) tentando sair: no-op.
    nome_ativo = next(j.username for j in lobby.partidas[-1].jogadores)
    c_ativo, chave_ativo = clis[nome_ativo]
    c_ativo.emit("sair_da_sala", {"chave": chave_ativo})
    lobby = modulo_store.carregar_sala(SALA)
    assert any(j.username == nome_ativo for j in lobby.jogadores), \
        "jogador ativo não pode sair via sair_da_sala"
    c_ativo.emit("sair_da_sala", {"chave": ""})
    assert any(j.username == nome_ativo for j in modulo_store.carregar_sala(SALA).jogadores), \
        "chave vazia é no-op para jogador registrado"
    _desconectar_todos(clis)
    _limpar()
    _ok("eliminado sai da partida e jogador ativo segue no-op (Fase 30)")


def verificar_integracao():
    print("5) integração flask_socketio.test_client (Fases 6, 7 e 15)")
    global modulo_store, modulo_app, funcoes_gerais, socketio, app
    modulo_store, modulo_app, funcoes_gerais = _preparar_integracao()
    from app import app, socketio  # noqa: F811 (rebind após preparar)

    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 0
    # Os testes genéricos exercitam o fluxo de jogo, não a política de defaults.
    # Com `verificacao_ativa` ligada no padrão, a sala só inicia com o reveal da
    # seed — e os clientes de teste não rodam JS. Congela os defaults "neutros"
    # (pré-política: verif desligada, sala pública, 1 dado) durante a integração;
    # os valores reais do padrão são validados em `verificar_roundtrip` e o
    # fluxo de seed tem teste próprio (commit-reveal) que liga a verificação.
    import modelos
    _padrao_original = modelos.Lobby.config_padrao
    modelos.Lobby.config_padrao = staticmethod(lambda: {
        'dados_qtd': 1,
        'max_jogadores': 6,
        'com_coringa': True,
        'publica': True,
        'substituir_desconectado_por_ia': False,
        'ia_nivel_padrao': 2,
        'verificacao_ativa': False,
        'tempo_max_jogada': 30,
    })
    testes_fase6 = [
        ("B3", teste_b3_aposta_invalida),
        ("B6", teste_b6_bools_reais),
        ("B1/B7", teste_b1_b7_desconexao_conferencia),
        ("B2", teste_b2_desconexao_vitoria),
        ("B4", teste_b4_vencedor_por_desconexao),
    ]
    testes_fase7 = [
        ("A3/A6", teste_a3_a6_chave_e_idempotencia),
        ("S1-const-time", teste_autenticar_comparacao_constant_time),
        ("V3", teste_v3_payloads_malformados),
        ("V2", teste_v2_cooldown),
        ("A4/A5", teste_a4_a5_lock_e_sorteio),
        ("partida completa", teste_partida_completa),
    ]
    testes_fase15 = [
        ("B1-gate", teste_gate_pagina_confirmacoes),
        ("B2-espectador", teste_espectador_nao_e_jogador),
        ("B3-bot-solo", teste_sala_so_com_bot_e_removida),
        ("GC-bot-persistido", teste_gc_unificado_sala_bot_sem_humano),
        ("busca-humanos", teste_busca_esconde_sala_sem_humano),
        ("heartbeat-resumo", teste_heartbeat_renova_resumo),
        ("heartbeat-sync", teste_heartbeat_resincroniza_lobby),
        ("heartbeat-espera-fresco", teste_heartbeat_espera_fresco_entre_instancias),
        ("B4-orfa-fechada", teste_sala_orfa_e_fechada),
        ("sala-padrao", teste_sala_padrao_fica_na_home),
    ]
    testes_hardening = [
        ("B6-resumo", teste_resumo_malformado_nao_quebra_busca),
        ("B8-cooldown", teste_cooldown_expurga_antigos),
        ("poda-partidas", teste_poda_partidas),
        ("json-tamanho-100-rodadas", teste_json_tamanho_bounded),
        ("upstash-indice", teste_upstash_indice_resumos),
        ("trava-distribuida", teste_trava_distribuida),
        ("revisao-cas", teste_revisao_cas),
        ("upstash-transporte", teste_upstash_transporte),
        ("leitura-segura-rede", teste_leitura_segura_falha_de_rede),
        ("og-dinamico", teste_index_og_dinamico),
        ("resumo-dedup", teste_resumo_dedup),
        ("H1-blob-corrompido", teste_h1_blob_corrompido),
        ("H1b-partida-vazia", teste_h1b_partida_vazia),
        ("H4-lock-secao-critica", teste_h4_lock_nao_reconfigura_na_secao_critica),
    ]
    testes_correcoes = [
        ("perdedor-cai", teste_conferencia_perdedor_desconectado),
        ("gate-aposta", teste_aposta_fora_da_pagina),
        ("master-bot", teste_master_apos_substituicao_ia),
        ("grace-espectador", teste_espectador_segura_grace),
        ("sala-sem-jogadores", teste_sala_sem_jogadores_promove_espectador),
        ("config-nome", teste_config_nome_roundtrip),
        ("conf-ok-cooldown", teste_conferencia_ok_sem_cooldown),
    ]
    testes_seed = [
        ("commit-reveal", teste_commit_reveal),
        ("reveal-cooldown", teste_revelar_seed_fora_do_cooldown),
    ]
    testes_expulsao = [
        ("expulsar-bot", teste_expulsar_bot),
        ("expulsar-humano", teste_expulsar_humano),
        ("expulsar-partida", teste_expulsar_durante_partida),
    ]
    testes_autojogar = [
        ("autojogar", teste_autojogar),
    ]
    testes_fase_d = [
        ("retomar-identidade", teste_retomar_identidade_por_evento),
        ("retomar-negado", teste_retomar_negado_chave_stale),
        ("refresh-conferencia-ok", teste_refresh_conferencia_preserva_ok),
        ("heartbeat-resync-vez", teste_heartbeat_resincroniza_vez_partida),
    ]
    testes_fase23 = [
        ("ultimo-humano-ia", teste_ultimo_humano_sala_de_ias_ganha_grace),
    ]
    testes_fase25 = [
        ("mq-wiring", teste_mq_wiring),
    ]
    testes_fase46 = [
        ("redis-store-wiring", teste_redis_store_wiring),
        ("redis-lock-fake", teste_redis_lock_fake),
    ]
    testes_fase29 = [
        ("H2-aposta-max", teste_h2_aposta_irrespondivel_clampeada),
        ("H3-cap-placeholder", teste_h3_cap_placeholder_nao_burla_limite),
    ]
    testes_fase30 = [
        ("volta-apos-substituicao", teste_volta_apos_substituicao_ia),
        ("grace-espera", teste_grace_espera_preserva_identidade),
        ("negado-vaga-perdida", teste_retomar_negado_vaga_perdida),
        ("inicio-sem-fantasma", teste_iniciar_sem_fantasma),
        ("iniciar-repetido-grace", teste_iniciar_repetido_nao_toca_grace),
        ("caido-sem-apelido", teste_iniciar_caido_sem_apelido_removido),
        ("sair-da-sala", teste_sair_da_sala_espectador),
        ("sair-da-sala-lobby", teste_sair_da_sala_lobby),
        ("sair-da-sala-eliminado", teste_sair_da_sala_eliminado),
        ("apelido-editavel", teste_apelido_editavel_ate_pronto),
    ]
    try:
        for nome, func in (testes_fase6 + testes_fase7 + testes_fase15
                           + testes_hardening + testes_correcoes + testes_seed
                           + testes_expulsao + testes_autojogar + testes_fase_d
                           + testes_fase23 + testes_fase25 + testes_fase46
                           + testes_fase29 + testes_fase30):
            try:
                func()
            except Exception as erro:  # noqa: BLE001 (agrega falhas dos testes)
                _falhou(nome, repr(erro))
    finally:
        modelos.Lobby.config_padrao = _padrao_original
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original


