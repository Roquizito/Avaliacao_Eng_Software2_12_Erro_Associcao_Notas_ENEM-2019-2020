"""
Modelos de domínio para a rotina de validação e matching de cadernos vs. cartões-resposta do ENEM.
Aborda o Caso 12 (Erro na Associação e Correção de Notas do ENEM 2019/2020).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CorCaderno(str, Enum):
    AZUL = "AZUL"
    AMARELO = "AMARELO"
    BRANCO = "BRANCO"
    ROSA = "ROSA"


class StatusValidacao(str, Enum):
    VALIDADO_CONSISTENTE = "VALIDADO_CONSISTENTE"
    VALIDADO_POR_FALLBACK = "VALIDADO_POR_FALLBACK"
    BLOQUEADO_INCONSISTENCIA_COR = "BLOQUEADO_INCONSISTENCIA_COR"
    BLOQUEADO_LOTE_CORROMPIDO = "BLOQUEADO_LOTE_CORROMPIDO"
    QUARENTENA_ANOMALIA_TRI = "QUARENTENA_ANOMALIA_TRI"


@dataclass(frozen=True)
class RegistroLoteGrafica:
    """
    Representa o registro enviado pela gráfica (ex.: Valid Soluções S.A.)
    após a impressão e montagem dos malotes.
    No incidente de 2019, uma falha na reimpressão deslocou o vínculo entre
    o código de barras do caderno e a cor associada ao candidato.
    """
    id_inscricao: str
    id_lote_impressao: str
    codigo_barras_caderno: str
    cor_associada_grafica: CorCaderno
    hash_frase_padrao_cor: str
    foi_reimpresso: bool = False


@dataclass(frozen=True)
class LeituraOpticaCartaoResposta:
    """
    Representa os dados extraídos da leitura óptica do cartão-resposta físico
    preenchido pelo estudante no dia da prova.
    """
    id_inscricao: str
    codigo_barras_cartao: str
    cor_marcada_aluno: Optional[CorCaderno]
    hash_frase_transcrita_aluno: Optional[str]
    respostas_questoes: str  # Ex: "ABCDE..." (90 questões do 2º dia)


@dataclass(frozen=True)
class RegistroAtaSala:
    """
    Representa o registro de controle de aplicação da sala (ata / lista de presença),
    que funciona como terceiro fator de conferência (3-Way Matching).
    """
    id_inscricao: str
    id_sala: str
    cor_distribuida_ata: CorCaderno
    presente: bool = True


@dataclass(frozen=True)
class ResultadoMatching:
    """
    Resultado imutável da rotina de validação e matching antes do cálculo da TRI.
    """
    id_inscricao: str
    id_lote_impressao: str
    status: StatusValidacao
    cor_confirmada: Optional[CorCaderno]
    pode_calcular_tri: bool
    motivo_detalhado: str
    divergencias_detectadas: List[str] = field(default_factory=list)
    nota_dia1_referencia: Optional[float] = None
    nota_dia2_calculada: Optional[float] = None
