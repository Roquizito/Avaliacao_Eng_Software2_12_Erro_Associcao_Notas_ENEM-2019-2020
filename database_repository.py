"""
Repositório de Banco de Dados (SQLite) com Constraints de Integridade e Triggers
que impedem o armazenamento de notas/gabaritos sem validação consistente de cores.

Demonstra na prática a camada de persistência para os Testes de Integração de Banco de Dados.
"""

import sqlite3
from typing import Dict, List, Optional
from interfaces import IRepositorioProcessamentoEnem
from models import CorCaderno, ResultadoMatching, StatusValidacao


class SQLiteRepositorioProcessamentoEnem(IRepositorioProcessamentoEnem):
    """
    Implementação concreta do repositório utilizando SQLite com constraints rígidas
    no próprio esquema relacional (Defense in Depth / Qualidade de Dados).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._criar_esquema_e_triggers()

    def _criar_esquema_e_triggers(self) -> None:
        with self._conn:
            # Tabela de auditoria e resultado de matching
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processamento_matching (
                    id_inscricao TEXT PRIMARY KEY,
                    id_lote_impressao TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cor_confirmada TEXT,
                    pode_calcular_tri INTEGER NOT NULL CHECK (pode_calcular_tri IN (0, 1)),
                    motivo_detalhado TEXT NOT NULL,
                    divergencias_json TEXT,
                    -- Constraint crítica de banco de dados:
                    -- Só permite pode_calcular_tri = 1 se cor_confirmada NÃO for nula
                    -- e se o status for explicitamente VALIDADO_CONSISTENTE ou VALIDADO_POR_FALLBACK
                    CHECK (
                        (pode_calcular_tri = 0)
                        OR (
                            pode_calcular_tri = 1
                            AND cor_confirmada IS NOT NULL
                            AND status IN ('VALIDADO_CONSISTENTE', 'VALIDADO_POR_FALLBACK')
                        )
                    )
                );
                """
            )

            # Tabela de lotes colocados em quarentena
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lotes_quarentena (
                    id_lote_impressao TEXT PRIMARY KEY,
                    motivo_bloqueio TEXT NOT NULL,
                    registros_afetados INTEGER NOT NULL
                );
                """
            )

            # Tabela de liberação de notas finais para o SISU
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notas_liberadas_sisu (
                    id_inscricao TEXT PRIMARY KEY,
                    cor_utilizada TEXT NOT NULL,
                    nota_dia2 REAL NOT NULL CHECK (nota_dia2 >= 0 AND nota_dia2 <= 1000),
                    FOREIGN KEY (id_inscricao) REFERENCES processamento_matching(id_inscricao)
                );
                """
            )

            # Trigger de banco de dados: bloqueia inserção em notas_liberadas_sisu
            # se o candidato estiver com pode_calcular_tri = 0 ou se a cor divergir
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_bloqueia_nota_sem_matching
                BEFORE INSERT ON notas_liberadas_sisu
                FOR EACH ROW
                BEGIN
                    SELECT CASE
                        WHEN (
                            SELECT pode_calcular_tri
                            FROM processamento_matching
                            WHERE id_inscricao = NEW.id_inscricao
                        ) IS NOT 1
                        THEN RAISE(ABORT, 'BLOQUEIO_DB: Tentativa de publicar nota sem matching de cor validado!')
                        WHEN (
                            SELECT cor_confirmada
                            FROM processamento_matching
                            WHERE id_inscricao = NEW.id_inscricao
                        ) != NEW.cor_utilizada
                        THEN RAISE(ABORT, 'BLOQUEIO_DB: Cor utilizada no cálculo difere da cor confirmada no matching!')
                    END;
                END;
                """
            )

    def salvar_resultado_matching(self, resultado: ResultadoMatching) -> None:
        divergencias_str = " | ".join(resultado.divergencias_detectadas)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO processamento_matching (
                    id_inscricao, id_lote_impressao, status, cor_confirmada,
                    pode_calcular_tri, motivo_detalhado, divergencias_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id_inscricao) DO UPDATE SET
                    status = excluded.status,
                    cor_confirmada = excluded.cor_confirmada,
                    pode_calcular_tri = excluded.pode_calcular_tri,
                    motivo_detalhado = excluded.motivo_detalhado,
                    divergencias_json = excluded.divergencias_json;
                """,
                (
                    resultado.id_inscricao,
                    resultado.id_lote_impressao,
                    resultado.status.value,
                    resultado.cor_confirmada.value if resultado.cor_confirmada else None,
                    1 if resultado.pode_calcular_tri else 0,
                    resultado.motivo_detalhado,
                    divergencias_str,
                ),
            )

    def bloquear_lote_inteiro(self, id_lote: str, motivo: str) -> int:
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE processamento_matching
                SET status = ?,
                    cor_confirmada = NULL,
                    pode_calcular_tri = 0,
                    motivo_detalhado = ?
                WHERE id_lote_impressao = ?;
                """,
                (StatusValidacao.BLOQUEADO_LOTE_CORROMPIDO.value, motivo, id_lote),
            )
            afetados = cursor.rowcount
            self._conn.execute(
                """
                INSERT OR REPLACE INTO lotes_quarentena (
                    id_lote_impressao, motivo_bloqueio, registros_afetados
                ) VALUES (?, ?, ?);
                """,
                (id_lote, motivo, afetados),
            )
            return afetados

    def publicar_nota_sisu(self, id_inscricao: str, cor_utilizada: CorCaderno, nota_dia2: float) -> None:
        """
        Tenta publicar a nota final do 2º dia na tabela do SISU.
        Se o matching não estiver validado ou a cor for trocada, o Trigger do banco
        dispara sqlite3.IntegrityError.
        """
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO notas_liberadas_sisu (id_inscricao, cor_utilizada, nota_dia2)
                VALUES (?, ?, ?);
                """,
                (id_inscricao, cor_utilizada.value, nota_dia2),
            )

    def buscar_registro(self, id_inscricao: str) -> Optional[Dict]:
        cur = self._conn.execute(
            "SELECT * FROM processamento_matching WHERE id_inscricao = ?;",
            (id_inscricao,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def fechar(self) -> None:
        self._conn.close()
