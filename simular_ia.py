"""
Simulador headless de partidas entre jogadores IA (Fase 11).

Não abre sockets: monta o Lobby direto no modelo e usa ia.processar para tocar a
partida inteira. Serve para verificar que o motor não trava/estoura e para
comparar o desempenho dos 4 níveis.

Uso (com a .venv, da raiz do repo):
    python simular_ia.py --partidas 40 --dados 3 --niveis 1,2,3,4
"""

import argparse

import funcoes_gerais
import ia
import modelos
import store
from modelos import Jogador, Lobby


def _silenciar_socket():
    """Fora de um request do Socket.IO não há room/namespace: neutraliza o emit.
    Fase 45 (M4): modelos virou pacote — o `emit` de cada submódulo é patcheado
    (cada um tem seu próprio binding); `funcoes_gerais` e o facade também."""
    import modelos.comum
    import modelos.jogador
    import modelos.turno
    import modelos.rodada
    import modelos.partida
    import modelos.lobby
    for modulo in (modelos, modelos.comum, modelos.jogador, modelos.turno,
                   modelos.rodada, modelos.partida, modelos.lobby, funcoes_gerais):
        if hasattr(modulo, 'emit'):
            modulo.emit = lambda *a, **k: None


def montar_partida(niveis, dados_qtd, com_coringa):
    lobby = Lobby(sala_id='sim', lobby_numero=1)
    lobby.config['dados_qtd'] = dados_qtd
    lobby.config['com_coringa'] = com_coringa
    lobby.config['max_jogadores'] = max(2, len(niveis))
    for indice, nivel in enumerate(niveis):
        jogador = Jogador.criar_ia(nivel, f"Bot{nivel}_{indice}")
        lobby.adicionar_jogador(jogador)
    lobby.jogadores[0].master = True
    partida = lobby.construir_partida(dados_qtd=dados_qtd)
    partida.construir_rodada()
    return lobby


def jogar(niveis, dados_qtd, com_coringa, rodadas_max=400):
    """Roda uma partida inteira e devolve o nível do vencedor (ou None)."""
    # Fase 52: o simulador cria um Lobby NOVO por partida com o mesmo sala_id
    # 'sim' — o rastreador de revisão (CAS) da instância precisaria continuar a
    # numeração entre partidas, mas o blob não persiste aqui (cada `montar_partida`
    # recomeça do 1). `remover_sala` zera o rastreador para a revisão recomeçar,
    # como aconteceria numa sala real criada do zero.
    store.remover_sala('sim')
    lobby = montar_partida(niveis, dados_qtd, com_coringa)
    for _ in range(rodadas_max):
        ia.processar(lobby)
        partida = lobby.partidas[-1]
        if partida.vencedor_final is not None:
            return partida.vencedor_final.ia_nivel
    raise RuntimeError('partida não terminou no limite de iterações')


def main():
    parser = argparse.ArgumentParser(description='Simulador de partidas entre jogadores IA.')
    parser.add_argument('--partidas', type=int, default=40)
    parser.add_argument('--dados', type=int, default=3)
    parser.add_argument('--niveis', type=str, default='1,2,3,4')
    parser.add_argument('--sem-coringa', action='store_true')
    args = parser.parse_args()

    _silenciar_socket()
    niveis = [int(n) for n in args.niveis.split(',') if n.strip()]
    if len(niveis) < 2:
        raise SystemExit('informe ao menos 2 níveis em --niveis (ex.: 1,2,3,4)')

    vitorias = {nivel: 0 for nivel in set(niveis)}
    for _ in range(args.partidas):
        vencedor = jogar(niveis, args.dados, not args.sem_coringa)
        if vencedor is not None:
            vitorias[vencedor] = vitorias.get(vencedor, 0) + 1

    print(f"Partidas: {args.partidas} · dados por jogador: {args.dados} · "
          f"coringa: {'nao' if args.sem_coringa else 'sim'} · niveis: {niveis}")
    for nivel in sorted(vitorias):
        pct = 100.0 * vitorias[nivel] / max(1, args.partidas)
        print(f"  Nível {nivel} ({ia.NOMES_NIVEIS.get(nivel, '?')}): "
              f"{vitorias[nivel]} vitórias ({pct:.1f}%)")


if __name__ == '__main__':
    main()
