"""Modelos do Dadinho (Fase 45, M4).

O arquivo único `modelos.py` virou um pacote por entidade (`lobby`, `partida`,
`rodada`, `turno`, `jogador`) + `comum` (sala_room/somente_ias) e `migracao`
(versão/migrações). Este facade re-exporta tudo para quem importa
`from modelos import ...` — nenhum import de fora muda.

O grafo de dependências é acíclico: `jogador`/`turno`/`migracao`/`comum` não
dependem de nada do pacote; `rodada` depende de `turno`+`comum`; `partida` de
`rodada`; `lobby` de todos.
"""
from flask_socketio import emit  # re-exportado p/ compat (simular_ia/verificar)

from modelos.comum import sala_room, somente_ias_na_partida
from modelos.jogador import Jogador
from modelos.migracao import (MIGRACOES, VAGAS_RECENTES_SEGUNDOS, VERSAO_ATUAL,
                              _migrar_v1_para_v2, _migrar_v2_para_v3,
                              _migrar_v3_para_v4, _migrar_v4_para_v5,
                              _migrar_v5_para_v6, _migrar_v6_para_v7,
                              _migrar_v7_para_v8)
from modelos.partida import Partida
from modelos.rodada import Rodada
from modelos.turno import Turno
from modelos.lobby import Lobby

__all__ = ['Lobby', 'Partida', 'Rodada', 'Turno', 'Jogador',
           'sala_room', 'somente_ias_na_partida', 'emit',
           'VERSAO_ATUAL', 'VAGAS_RECENTES_SEGUNDOS', 'MIGRACOES',
           '_migrar_v1_para_v2', '_migrar_v2_para_v3', '_migrar_v3_para_v4',
           '_migrar_v4_para_v5', '_migrar_v5_para_v6', '_migrar_v6_para_v7',
           '_migrar_v7_para_v8']