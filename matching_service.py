"""
Serviço de Validação e Matching Triplo (3-Way Matching) de Cadernos vs. Cartões-Resposta
e Portão de Qualidade Estatística (Sanity Check da TRI).

Este módulo implementa a solução proposta na Etapa 3 para o Caso 12 (ENEM 2019/2020).
"""

from typing import List, Optional, Tuple
from interfaces import (
    IAlertaQualidadeNotifier,
    IGabaritoOficialProvider,
    IRepositorioProcessamentoEnem,
)
from models import (
    CorCaderno,
    LeituraOpticaCartaoResposta,
    RegistroAtaSala,
    RegistroLoteGrafica,
    ResultadoMatching,
    StatusValidacao,
)


class ValidadorMatchingEnem:
    """
    Responsável exclusivamente (SRP - Single Responsibility Principle) por validar a
    consistência entre a cor informada pela gráfica, a leitura óptica do cartão-resposta
    do candidato e a ata de sala antes de autorizar o cálculo de nota na TRI.
    """

    LIMIAR_TAXA_ERRO_LOTE = 0.005  # 0.5% de divergência no lote bloqueia o lote inteiro
    LIMIAR_DISCREPANCIA_INTER_DIAS = 320.0  # Queda > 320 pontos entre Dia 1 e Dia 2 gera alerta

    def __init__(
        self,
        gabarito_provider: IGabaritoOficialProvider,
        repositorio: IRepositorioProcessamentoEnem,
        alerta_notifier: IAlertaQualidadeNotifier,
    ) -> None:
        self._gabarito_provider = gabarito_provider
        self._repositorio = repositorio
        self._alerta_notifier = alerta_notifier

    def validar_candidato(
        self,
        registro_grafica: RegistroLoteGrafica,
        cartao_resposta: LeituraOpticaCartaoResposta,
        ata_sala: Optional[RegistroAtaSala] = None,
    ) -> ResultadoMatching:
        """
        Realiza o 3-Way Matching entre:
        1. Cor vinculada no lote da gráfica (sujeita a bug de offset em reimpressão).
        2. Cor marcada pelo candidato no cartão-resposta + frase de segurança da capa.
        3. Cor registrada na ata/sequência de distribuição da sala.
        """
        if registro_grafica.id_inscricao != cartao_resposta.id_inscricao:
            raise ValueError(
                f"Violação de chave primária: inscrição da gráfica ({registro_grafica.id_inscricao}) "
                f"difere do cartão-resposta ({cartao_resposta.id_inscricao})."
            )

        divergencias: List[str] = []
        cor_grafica = registro_grafica.cor_associada_grafica
        cor_cartao = cartao_resposta.cor_marcada_aluno

        # 1. Conferência da frase de segurança transcrita pelo aluno vs. gabarito oficial
        cor_pela_frase: Optional[CorCaderno] = self._identificar_cor_por_frase(
            cartao_resposta.hash_frase_transcrita_aluno
        )

        # 2. Verificação de divergência entre Gráfica e Cartão-Resposta (o erro central de 2019)
        if cor_cartao is not None and cor_cartao != cor_grafica:
            divergencias.append(
                f"Divergência de cor: Gráfica informou {cor_grafica.value}, "
                f"mas cartão-resposta indica {cor_cartao.value}."
            )

        if cor_pela_frase is not None and cor_pela_frase != cor_grafica:
            divergencias.append(
                f"Divergência de frase de segurança: Frase transcrita pertence ao caderno "
                f"{cor_pela_frase.value}, mas gráfica vinculou {cor_grafica.value}."
            )

        if ata_sala is not None and ata_sala.cor_distribuida_ata != cor_grafica:
            divergencias.append(
                f"Divergência na ata de sala: Ata indica {ata_sala.cor_distribuida_ata.value}, "
                f"mas gráfica vinculou {cor_grafica.value}."
            )

        # Caso 1: Todos os indicadores presentes concordam com a gráfica -> Consistente
        if not divergencias and (cor_cartao == cor_grafica and cor_pela_frase == cor_grafica):
            resultado = ResultadoMatching(
                id_inscricao=registro_grafica.id_inscricao,
                id_lote_impressao=registro_grafica.id_lote_impressao,
                status=StatusValidacao.VALIDADO_CONSISTENTE,
                cor_confirmada=cor_grafica,
                pode_calcular_tri=True,
                motivo_detalhado="Matching triplo consistente entre gráfica, cartão e frase.",
                divergencias_detectadas=[],
            )
            self._repositorio.salvar_resultado_matching(resultado)
            return resultado

        # Caso 2: Aluno esqueceu de marcar a bolinha da cor no cartão, mas a frase e a ata
        # concordam com a gráfica (Fallback seguro para erro humano do candidato)
        if (
            cor_cartao is None
            and cor_pela_frase == cor_grafica
            and (ata_sala is None or ata_sala.cor_distribuida_ata == cor_grafica)
        ):
            resultado = ResultadoMatching(
                id_inscricao=registro_grafica.id_inscricao,
                id_lote_impressao=registro_grafica.id_lote_impressao,
                status=StatusValidacao.VALIDADO_POR_FALLBACK,
                cor_confirmada=cor_grafica,
                pode_calcular_tri=True,
                motivo_detalhado=(
                    "Candidato omitiu marcação de cor, mas frase de segurança e ata "
                    "confirmam a cor da gráfica."
                ),
                divergencias_detectadas=[],
            )
            self._repositorio.salvar_resultado_matching(resultado)
            return resultado

        # Caso 3: Há divergência entre a gráfica e os dados físicos do cartão/ata
        # Bloqueia imediatamente o cálculo da TRI com gabarito errado!
        resultado = ResultadoMatching(
            id_inscricao=registro_grafica.id_inscricao,
            id_lote_impressao=registro_grafica.id_lote_impressao,
            status=StatusValidacao.BLOQUEADO_INCONSISTENCIA_COR,
            cor_confirmada=None,
            pode_calcular_tri=False,
            motivo_detalhado=(
                "Processamento bloqueado: falha no matching entre lote da gráfica e "
                "evidências físicas do cartão-resposta."
            ),
            divergencias_detectadas=divergencias,
        )
        self._repositorio.salvar_resultado_matching(resultado)
        return resultado

    def processar_lote_com_circuit_breaker(
        self,
        lote: List[Tuple[RegistroLoteGrafica, LeituraOpticaCartaoResposta, Optional[RegistroAtaSala]]],
    ) -> List[ResultadoMatching]:
        """
        Processa um lote inteiro vindo da gráfica. Se a taxa de divergência de cores
        ultrapassar o limiar de segurança (0,5%), aciona o Circuit Breaker de banco de dados,
        colocando todo o lote em quarentena (evitando que falhas de reimpressão passem).
        """
        if not lote:
            return []

        id_lote = lote[0][0].id_lote_impressao
        resultados: List[ResultadoMatching] = []
        total_inconsistentes = 0

        for reg_grafica, cartao, ata in lote:
            res = self.validar_candidato(reg_grafica, cartao, ata)
            if not res.pode_calcular_tri:
                total_inconsistentes += 1
            resultados.append(res)

        taxa_erro = total_inconsistentes / len(lote)
        if taxa_erro > self.LIMIAR_TAXA_ERRO_LOTE:
            motivo_bloqueio = (
                f"Taxa de divergência de cores no lote {id_lote} ({taxa_erro:.1%}) "
                f"excedeu o limite máximo de {self.LIMIAR_TAXA_ERRO_LOTE:.1%}. "
                f"Suspeita de deslocamento (offset) em reimpressão gráfica."
            )
            self._repositorio.bloquear_lote_inteiro(id_lote, motivo_bloqueio)
            self._alerta_notifier.emitir_alerta_critico(id_lote, taxa_erro, motivo_bloqueio)

        return resultados

    def auditar_anomalia_estatistica_tri(
        self,
        resultado_previo: ResultadoMatching,
        nota_media_dia1_e_redacao: float,
        nota_calculada_dia2: float,
    ) -> ResultadoMatching:
        """
        Portão de Qualidade (Quality Gate) pós-cálculo da TRI e pré-divulgação:
        Detecta se um candidato com alto desempenho no 1º dia + Redação teve queda
        estatisticamente improvável no 2º dia (padrão clássico de gabarito trocado).
        """
        queda = nota_media_dia1_e_redacao - nota_calculada_dia2
        if nota_media_dia1_e_redacao >= 700.0 and queda >= self.LIMIAR_DISCREPANCIA_INTER_DIAS:
            resultado_quarentena = ResultadoMatching(
                id_inscricao=resultado_previo.id_inscricao,
                id_lote_impressao=resultado_previo.id_lote_impressao,
                status=StatusValidacao.QUARENTENA_ANOMALIA_TRI,
                cor_confirmada=resultado_previo.cor_confirmada,
                pode_calcular_tri=False,
                motivo_detalhado=(
                    f"Anomalia estatística detectada antes da publicação: Média Dia 1/Redação "
                    f"({nota_media_dia1_e_redacao:.1f}) vs. Nota Dia 2 ({nota_calculada_dia2:.1f}). "
                    f"Queda de {queda:.1f} pontos requer auditoria do espelho físico."
                ),
                divergencias_detectadas=list(resultado_previo.divergencias_detectadas)
                + [f"Discrepância estatística inter-dias: -{queda:.1f} pts"],
                nota_dia1_referencia=nota_media_dia1_e_redacao,
                nota_dia2_calculada=nota_calculada_dia2,
            )
            self._repositorio.salvar_resultado_matching(resultado_quarentena)
            return resultado_quarentena

        return resultado_previo

    def _identificar_cor_por_frase(self, hash_frase: Optional[str]) -> Optional[CorCaderno]:
        if not hash_frase:
            return None
        for cor in CorCaderno:
            if self._gabarito_provider.obter_hash_frase_oficial(cor) == hash_frase:
                return cor
        return None
