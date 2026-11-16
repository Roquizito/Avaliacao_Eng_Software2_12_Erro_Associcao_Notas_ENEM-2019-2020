"""
Interfaces (contratos estáveis) para inversão de dependência (SOLID - DIP e ISP).
Permitem desacoplar a regra de validação de cores/gabaritos do banco de dados
e do sistema externo da gráfica.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from models import (
    CorCaderno,
    LeituraOpticaCartaoResposta,
    RegistroAtaSala,
    RegistroLoteGrafica,
    ResultadoMatching,
)


class IGabaritoOficialProvider(ABC):
    """Interface para obtenção dos gabaritos oficiais e frases de segurança por cor."""

    @abstractmethod
    def obter_hash_frase_oficial(self, cor: CorCaderno) -> str:
        """Retorna o hash oficial da frase de segurança impressa na capa de cada cor."""
        pass

    @abstractmethod
    def obter_gabarito_oficial(self, cor: CorCaderno) -> str:
        """Retorna a string de respostas corretas para a cor do caderno."""
        pass


class IRepositorioProcessamentoEnem(ABC):
    """Interface de persistência para lotes, resultados de matching e auditoria."""

    @abstractmethod
    def salvar_resultado_matching(self, resultado: ResultadoMatching) -> None:
        """Persiste o resultado validado ou bloqueado garantindo integridade transacional."""
        pass

    @abstractmethod
    def bloquear_lote_inteiro(self, id_lote: str, motivo: str) -> int:
        """Coloca todos os registros de um lote suspeito em quarentena."""
        pass


class IAlertaQualidadeNotifier(ABC):
    """Interface para disparo de alertas à equipe de Qualidade do Inep."""

    @abstractmethod
    def emitir_alerta_critico(self, id_lote: str, taxa_erro: float, mensagem: str) -> None:
        """Notifica a equipe técnica quando um lote ultrapassa o limite de divergências."""
        pass
