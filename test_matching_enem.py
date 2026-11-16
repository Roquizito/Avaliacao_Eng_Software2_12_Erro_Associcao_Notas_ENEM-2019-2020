"""
Suíte de Testes Automatizados (Unitários com Mocks e Integração com Banco de Dados)
para a rotina de validação e matching de cores vs. cadernos do ENEM (Caso 12).

Execução:
    python3 -m unittest -v test_matching_enem.py
"""

import sqlite3
import unittest
from unittest.mock import MagicMock

from database_repository import SQLiteRepositorioProcessamentoEnem
from interfaces import (
    IAlertaQualidadeNotifier,
    IGabaritoOficialProvider,
    IRepositorioProcessamentoEnem,
)
from matching_service import ValidadorMatchingEnem
from models import (
    CorCaderno,
    LeituraOpticaCartaoResposta,
    RegistroAtaSala,
    RegistroLoteGrafica,
    StatusValidacao,
)


class FakeGabaritoProvider(IGabaritoOficialProvider):
    """Provedor determinístico de hashes das frases de segurança de cada cor."""

    HASHES = {
        CorCaderno.AZUL: "HASH_FRASE_AZUL_2019",
        CorCaderno.AMARELO: "HASH_FRASE_AMARELO_2019",
        CorCaderno.BRANCO: "HASH_FRASE_BRANCO_2019",
        CorCaderno.ROSA: "HASH_FRASE_ROSA_2019",
    }

    def obter_hash_frase_oficial(self, cor: CorCaderno) -> str:
        return self.HASHES[cor]

    def obter_gabarito_oficial(self, cor: CorCaderno) -> str:
        return "A" * 90


class TestUnitarioMatchingEnem(unittest.TestCase):
    """
    CAMADA 1 DA PIRÂMIDE: TESTES DE UNIDADE (COM MOCKS)
    Isolam a lógica de domínio do ValidadorMatchingEnem usando Mocks para o repositório
    e para o serviço de alertas.
    """

    def setUp(self) -> None:
        self.gabarito_provider = FakeGabaritoProvider()
        self.mock_repo = MagicMock(spec=IRepositorioProcessamentoEnem)
        self.mock_notifier = MagicMock(spec=IAlertaQualidadeNotifier)
        self.validador = ValidadorMatchingEnem(
            gabarito_provider=self.gabarito_provider,
            repositorio=self.mock_repo,
            alerta_notifier=self.mock_notifier,
        )

    def test_01_matching_perfeito_autoriza_calculo_tri(self) -> None:
        """Caminho feliz: Gráfica, Cartão-Resposta, Frase e Ata indicam caderno AZUL."""
        reg_grafica = RegistroLoteGrafica(
            id_inscricao="190001001",
            id_lote_impressao="LOTE_SP_01",
            codigo_barras_caderno="CB-99881",
            cor_associada_grafica=CorCaderno.AZUL,
            hash_frase_padrao_cor="HASH_FRASE_AZUL_2019",
        )
        cartao = LeituraOpticaCartaoResposta(
            id_inscricao="190001001",
            codigo_barras_cartao="CR-99881",
            cor_marcada_aluno=CorCaderno.AZUL,
            hash_frase_transcrita_aluno="HASH_FRASE_AZUL_2019",
            respostas_questoes="ABCDE" * 18,
        )
        ata = RegistroAtaSala(
            id_inscricao="190001001",
            id_sala="SALA-101",
            cor_distribuida_ata=CorCaderno.AZUL,
        )

        resultado = self.validador.validar_candidato(reg_grafica, cartao, ata)

        self.assertTrue(resultado.pode_calcular_tri)
        self.assertEqual(resultado.status, StatusValidacao.VALIDADO_CONSISTENTE)
        self.assertEqual(resultado.cor_confirmada, CorCaderno.AZUL)
        self.assertEqual(len(resultado.divergencias_detectadas), 0)
        self.mock_repo.salvar_resultado_matching.assert_called_once_with(resultado)

    def test_02_bloqueia_bug_enem_2019_troca_cor_na_grafica(self) -> None:
        """
        Cenário exato do Bug do ENEM 2019 (Caso 12):
        Na reimpressão da gráfica, o lote associou AMARELO ao candidato, mas o aluno
        recebeu, marcou e transcreveu a frase da prova BRANCA.
        """
        reg_grafica_corrompido = RegistroLoteGrafica(
            id_inscricao="190005974",
            id_lote_impressao="LOTE_REIMPRESSO_VALID_42",
            codigo_barras_caderno="CB-OFFSET-01",
            cor_associada_grafica=CorCaderno.AMARELO,  # Cor errada associada pela gráfica
            hash_frase_padrao_cor="HASH_FRASE_AMARELO_2019",
            foi_reimpresso=True,
        )
        cartao_aluno = LeituraOpticaCartaoResposta(
            id_inscricao="190005974",
            codigo_barras_cartao="CR-OFFSET-01",
            cor_marcada_aluno=CorCaderno.BRANCO,  # Aluno fez prova BRANCA
            hash_frase_transcrita_aluno="HASH_FRASE_BRANCO_2019",
            respostas_questoes="BDECA" * 18,
        )

        resultado = self.validador.validar_candidato(reg_grafica_corrompido, cartao_aluno)

        self.assertFalse(resultado.pode_calcular_tri)
        self.assertIsNone(resultado.cor_confirmada)
        self.assertEqual(resultado.status, StatusValidacao.BLOQUEADO_INCONSISTENCIA_COR)
        self.assertEqual(len(resultado.divergencias_detectadas), 2)
        self.mock_repo.salvar_resultado_matching.assert_called_once()

    def test_03_fallback_seguro_quando_aluno_esquece_bolinha_mas_transcreve_frase(self) -> None:
        """
        Trade-off tratado: Aluno esqueceu de preencher a bolinha da cor no cartão (None),
        mas transcreveu a frase da capa ROSA e a ata de sala confirma ROSA.
        """
        reg_grafica = RegistroLoteGrafica(
            id_inscricao="190002002",
            id_lote_impressao="LOTE_RJ_05",
            codigo_barras_caderno="CB-2002",
            cor_associada_grafica=CorCaderno.ROSA,
            hash_frase_padrao_cor="HASH_FRASE_ROSA_2019",
        )
        cartao_sem_bolinha = LeituraOpticaCartaoResposta(
            id_inscricao="190002002",
            codigo_barras_cartao="CR-2002",
            cor_marcada_aluno=None,
            hash_frase_transcrita_aluno="HASH_FRASE_ROSA_2019",
            respostas_questoes="CDAEB" * 18,
        )
        ata = RegistroAtaSala(
            id_inscricao="190002002",
            id_sala="SALA-204",
            cor_distribuida_ata=CorCaderno.ROSA,
        )

        resultado = self.validador.validar_candidato(reg_grafica, cartao_sem_bolinha, ata)

        self.assertTrue(resultado.pode_calcular_tri)
        self.assertEqual(resultado.status, StatusValidacao.VALIDADO_POR_FALLBACK)
        self.assertEqual(resultado.cor_confirmada, CorCaderno.ROSA)

    def test_04_rejeita_violacao_chave_primaria_entre_grafica_e_cartao(self) -> None:
        """Garante que um pareamento com IDs de inscrição distintos lance exceção."""
        reg_grafica = RegistroLoteGrafica(
            id_inscricao="190009991",
            id_lote_impressao="LOTE_01",
            codigo_barras_caderno="CB-1",
            cor_associada_grafica=CorCaderno.AZUL,
            hash_frase_padrao_cor="HASH_FRASE_AZUL_2019",
        )
        cartao_outro_aluno = LeituraOpticaCartaoResposta(
            id_inscricao="190009992",
            codigo_barras_cartao="CR-2",
            cor_marcada_aluno=CorCaderno.AZUL,
            hash_frase_transcrita_aluno="HASH_FRASE_AZUL_2019",
            respostas_questoes="A" * 90,
        )

        with self.assertRaises(ValueError):
            self.validador.validar_candidato(reg_grafica, cartao_outro_aluno)

    def test_05_circuit_breaker_bloqueia_lote_quando_taxa_erro_excede_limite(self) -> None:
        """
        Verifica se um lote com > 0.5% de divergências aciona o bloqueio do lote inteiro
        e dispara alerta crítico para a equipe de Qualidade do Inep.
        """
        lote = [
            # Aluno 1: Consistente
            (
                RegistroLoteGrafica("101", "LOTE_DEFEITUOSO_99", "CB1", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019"),
                LeituraOpticaCartaoResposta("101", "CR1", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019", "A" * 90),
                None,
            ),
            # Aluno 2: Inconsistente (1 em 2 = 50% > 0.5%)
            (
                RegistroLoteGrafica("102", "LOTE_DEFEITUOSO_99", "CB2", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019"),
                LeituraOpticaCartaoResposta("102", "CR2", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019", "B" * 90),
                None,
            ),
        ]

        self.validador.processar_lote_com_circuit_breaker(lote)

        self.mock_repo.bloquear_lote_inteiro.assert_called_once()
        self.mock_notifier.emitir_alerta_critico.assert_called_once()

    def test_06_portao_qualidade_estatistica_detecta_anomalia_tri_inter_dias(self) -> None:
        """
        Verifica se um candidato com média 810 no Dia 1/Redação que aparece com 340 no Dia 2
        é retido automaticamente na quarentena estatística antes da publicação.
        """
        reg_grafica = RegistroLoteGrafica("190007777", "LOTE_07", "CB7", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019")
        cartao = LeituraOpticaCartaoResposta("190007777", "CR7", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019", "A" * 90)
        res_previo = self.validador.validar_candidato(reg_grafica, cartao)

        res_auditado = self.validador.auditar_anomalia_estatistica_tri(
            resultado_previo=res_previo,
            nota_media_dia1_e_redacao=810.0,
            nota_calculada_dia2=340.5,
        )

        self.assertFalse(res_auditado.pode_calcular_tri)
        self.assertEqual(res_auditado.status, StatusValidacao.QUARENTENA_ANOMALIA_TRI)


class TestIntegracaoBancoDadosEnem(unittest.TestCase):
    """
    CAMADA 2 DA PIRÂMIDE: TESTES DE INTEGRAÇÃO COM BANCO DE DADOS
    Testam a integração real entre ValidadorMatchingEnem e SQLiteRepositorioProcessamentoEnem,
    validando Constraints, Triggers e bloqueio transacional em lote.
    """

    def setUp(self) -> None:
        self.repo_db = SQLiteRepositorioProcessamentoEnem(":memory:")
        self.gabarito_provider = FakeGabaritoProvider()
        self.mock_notifier = MagicMock(spec=IAlertaQualidadeNotifier)
        self.validador = ValidadorMatchingEnem(
            gabarito_provider=self.gabarito_provider,
            repositorio=self.repo_db,
            alerta_notifier=self.mock_notifier,
        )

    def tearDown(self) -> None:
        self.repo_db.fechar()

    def test_07_integracao_db_permite_publicar_nota_sisu_apenas_para_matching_valido(self) -> None:
        """Garante que notas com matching validado sejam gravadas na tabela do SISU."""
        reg = RegistroLoteGrafica("2001", "LOTE_OK", "CB2001", CorCaderno.BRANCO, "HASH_FRASE_BRANCO_2019")
        cartao = LeituraOpticaCartaoResposta("2001", "CR2001", CorCaderno.BRANCO, "HASH_FRASE_BRANCO_2019", "A" * 90)

        self.validador.validar_candidato(reg, cartao)
        # Deve permitir publicar a nota usando a mesma cor confirmada (BRANCO)
        self.repo_db.publicar_nota_sisu("2001", CorCaderno.BRANCO, 745.8)

        registro_salvo = self.repo_db.buscar_registro("2001")
        self.assertIsNotNone(registro_salvo)
        self.assertEqual(registro_salvo["pode_calcular_tri"], 1)
        self.assertEqual(registro_salvo["cor_confirmada"], "BRANCO")

    def test_08_trigger_db_bloqueia_publicacao_de_nota_com_cor_divergente(self) -> None:
        """
        Verifica se a Trigger SQLite `trg_bloqueia_nota_sem_matching` aborta a transação
        caso tentem publicar no SISU a nota de um candidato bloqueado por divergência de cor.
        """
        reg_errado = RegistroLoteGrafica("2002", "LOTE_BUG", "CB2002", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019")
        cartao_rosa = LeituraOpticaCartaoResposta("2002", "CR2002", CorCaderno.ROSA, "HASH_FRASE_ROSA_2019", "A" * 90)

        self.validador.validar_candidato(reg_errado, cartao_rosa)

        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.repo_db.publicar_nota_sisu("2002", CorCaderno.AZUL, 320.0)

        self.assertIn("BLOQUEIO_DB", str(ctx.exception))

    def test_09_trigger_db_bloqueia_troca_de_cor_na_hora_de_calcular_nota(self) -> None:
        """
        Mesmo que o candidato tenha sido validado como AZUL, se a rotina de cálculo tentar
        gravar uma nota calculada com o gabarito AMARELO, o banco de dados bloqueia.
        """
        reg = RegistroLoteGrafica("2003", "LOTE_OK", "CB2003", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019")
        cartao = LeituraOpticaCartaoResposta("2003", "CR2003", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019", "A" * 90)

        self.validador.validar_candidato(reg, cartao)

        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.repo_db.publicar_nota_sisu("2003", CorCaderno.AMARELO, 410.0)

        self.assertIn("Cor utilizada no cálculo difere da cor confirmada", str(ctx.exception))

    def test_10_quarentena_em_lote_revoga_autorizacao_de_todos_candidatos_do_lote(self) -> None:
        """
        Simula um lote reimpresso onde o primeiro aluno parecia consistente por coincidência,
        mas o segundo revelou o deslocamento de cores. O Circuit Breaker deve invalidar
        todo o lote no banco de dados, impedindo que qualquer aluno daquele lote vá para o SISU.
        """
        lote_reimpresso = [
            (
                RegistroLoteGrafica("3001", "LOTE_REIMP_55", "CB3001", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019"),
                LeituraOpticaCartaoResposta("3001", "CR3001", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019", "A" * 90),
                None,
            ),
            (
                RegistroLoteGrafica("3002", "LOTE_REIMP_55", "CB3002", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019"),
                LeituraOpticaCartaoResposta("3002", "CR3002", CorCaderno.BRANCO, "HASH_FRASE_BRANCO_2019", "B" * 90),
                None,
            ),
        ]

        self.validador.processar_lote_com_circuit_breaker(lote_reimpresso)

        # Até mesmo o candidato 3001 (que pertence ao lote corrompido) deve estar bloqueado no DB
        reg_3001 = self.repo_db.buscar_registro("3001")
        self.assertEqual(reg_3001["status"], StatusValidacao.BLOQUEADO_LOTE_CORROMPIDO.value)
        self.assertEqual(reg_3001["pode_calcular_tri"], 0)

        with self.assertRaises(sqlite3.IntegrityError):
            self.repo_db.publicar_nota_sisu("3001", CorCaderno.AZUL, 680.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
