import dataclasses
import datetime
import enum
import functools
import random
import typing

import arrow
import numpy as np
import simpy

import sd
from sd import Modelo


def generate_random_integers(n: int, x: int) -> list[int]:
    if n == 1:
        return [x]

    # Generate n-1 random boundaries between 0 and x
    boundaries = sorted(random.randint(0, x) for _ in range(n - 1))

    # Calculate the differences between the boundaries
    random_integers = [boundaries[0]] + \
                      [boundaries[i] - boundaries[i - 1] for i in range(1, n - 1)] + \
                      [x - boundaries[-1]]

    return random_integers


@dataclasses.dataclass(frozen=True, kw_only=True)
class Van:
    id: int


def _f(values: list[int], valor_max: int) -> list[int] | None:
    for i in range(len(values)):
        valores_prefixo = values[:i + 1]
        soma_prefixo = sum(valores_prefixo)
        if soma_prefixo < valor_max:
            continue
        i = -1 if soma_prefixo > valor_max else None
        return valores_prefixo[:i]
    return None


class _Metrica(enum.Enum):
    TEMPO_ESPERA_ESTACIONAR = 0
    TEMPO_ESPERA_ABERTURA = 1
    TEMPO_ESPERA_DESCARREGAR = 2
    TEMPO_DESCARREGAR = 3
    TEMPO_ESPERA_AREA_CARGA = 4
    TEMPO_ESPERA_CARREGAR = 5
    TEMPO_CARREGAR = 6


@dataclasses.dataclass
class Carregamento:
    volumes: list[float]
    evento_conclusao: simpy.Event


class ModeloCentroDistribuicao(sd.Modelo[_Metrica]):
    @dataclasses.dataclass(kw_only=True)
    class _Estatisticas:
        tempos_espera_estacionar: list[float]
        tempos_espera_abertura: list[float]
        tempos_espera_descarregar: list[float]
        tempos_descarregar: list[float]
        tempos_espera_area_carga: list[float]
        tempos_espera_carregar: list[float]
        tempos_carregar: list[float]

    @typing.override
    def calcula_metrica(self, metrica: _Metrica) -> list[float]:
        match metrica:
            case _Metrica.TEMPO_ESPERA_ESTACIONAR:
                return self._estatisticas.tempos_espera_estacionar
            case _Metrica.TEMPO_ESPERA_ABERTURA:
                return self._estatisticas.tempos_espera_abertura
            case _Metrica.TEMPO_ESPERA_DESCARREGAR:
                return self._estatisticas.tempos_espera_descarregar
            case _Metrica.TEMPO_DESCARREGAR:
                return self._estatisticas.tempos_descarregar
            case _Metrica.TEMPO_ESPERA_AREA_CARGA:
                return self._estatisticas.tempos_espera_area_carga
            case _Metrica.TEMPO_ESPERA_CARREGAR:
                return self._estatisticas.tempos_espera_carregar
            case _Metrica.TEMPO_CARREGAR:
                return self._estatisticas.tempos_carregar
            case _:
                typing.assert_never(metrica)

    _estatisticas: _Estatisticas

    _qtd_max_caminhoes: int
    _qtd_vans: int
    _qtd_funcionarios: int
    _tamanho_caminhao: int
    _tamanho_van: int
    _tamanho_deposito: int
    _velocidade_descarga: int
    _velocidade_carga: int

    _hora_inicio_funcionamento: int
    # A empresa funciona 8h por dia para carga e descarga
    _duracao_funcionamento: typing.Final[int] = 8

    @property
    def _hora_final_funcionamento(self):
        return self._hora_inicio_funcionamento + self._duracao_funcionamento

    _resource_descarga_caminhoes: simpy.Resource
    _resource_estacionamento_caminhoes: simpy.Resource
    _resource_carga_vans: simpy.Resource

    _store_deposito: simpy.Store
    _store_vans: simpy.Store
    _container_deposito: simpy.Container

    _evento_iniciar_carga: simpy.Event
    _evento_iniciar_descarga: simpy.Event
    _evento_finalizar_carga: simpy.Event
    _evento_finalizar_descarga: simpy.Event

    def __init__(
            self,
            *,
            seed: int | None = None,
            deve_exibir_log: bool = False,
            qtd_max_caminhoes: int,
            qtd_vans: int,
            qtd_funcionarios: int,
            tamanho_caminhao: int,
            tamanho_van: int,
            tamanho_deposito: int,
            velocidade_descarga: int,
            velocidade_carga: int,
    ) -> None:
        super().__init__(
            seed=seed,
            deve_exibir_log=deve_exibir_log,
        )
        self._hora_inicio_funcionamento = 8  # 08AM
        self._qtd_max_caminhoes = qtd_max_caminhoes
        self._qtd_vans = qtd_vans
        self._qtd_funcionarios = qtd_funcionarios
        self._tamanho_caminhao = tamanho_caminhao
        self._tamanho_van = tamanho_van
        self._tamanho_deposito = tamanho_deposito
        self._velocidade_descarga = velocidade_descarga
        self._velocidade_carga = velocidade_carga

    @typing.override
    def inicia(self, env: simpy.Environment) -> None:
        self._estatisticas = ModeloCentroDistribuicao._Estatisticas(
            tempos_espera_estacionar=[],
            tempos_espera_abertura=[],
            tempos_espera_descarregar=[],
            tempos_descarregar=[],
            tempos_espera_area_carga=[],
            tempos_espera_carregar=[],
            tempos_carregar=[],
        )

        # O depósito pode armazenar 300m³
        self._store_deposito = simpy.Store(env)
        self._container_deposito = simpy.Container(env, capacity=self._tamanho_deposito)

        # Só existe um ponto de descarga de caminhões
        self._resource_descarga_caminhoes = simpy.Resource(env, capacity=1)
        # e um pátio para estacionar 5 caminhões
        self._resource_estacionamento_caminhoes = simpy.Resource(env, capacity=self._qtd_max_caminhoes)

        # Existe um outro ponto para carga de uma van
        self._resource_carga_vans = simpy.Resource(env, capacity=1)

        self._evento_iniciar_carga = env.event()
        self._evento_iniciar_descarga = env.event()
        self._evento_finalizar_carga = env.event()
        self._evento_finalizar_descarga = env.event()
        self._store_eventos_carregamento = simpy.Store(env)

        env.process(self._processa_funcionarios__carregamento(env))
        env.process(self._processa_caminhao(env))
        env.process(self._processa_funcionarios__(env))
        # A empresa possui 4 vans
        for idx_van in range(self._qtd_vans):
            env.process(self._processa_van(env, Van(id=idx_van + 1)))

    _store_eventos_carregamento: simpy.Store

    def _processa_funcionarios__(self, env: simpy.Environment) -> sd.Generator:
        log = functools.partial(self._log, env, f'equipe')
        while True:
            volumes: list[float] = []
            while sum(volumes) < self._tamanho_van:
                volume = yield self._store_deposito.get()
                yield self._container_deposito.get(volume)
                volumes.append(volume)

            if True:
                # Existem caixas o suficiente no depósito para carregar uma van

                dt_hoje = arrow.get(datetime.datetime.now().date())
                dt_agora = dt_hoje.shift(hours=env.now % 24)
                dt_maximo = dt_hoje.replace(hour=self._hora_final_funcionamento)
                dt_fim_carga = dt_agora.shift(hours=len(volumes) / self._qtd_funcionarios / self._velocidade_carga)

                if dt_fim_carga <= dt_maximo:
                    # Uma carga só pode começar se ela for terminar
                    # antes do horário de término do serviço
                    log(f'aprova carregamento de {len(volumes)} caixas, com {sum(volumes):.2f} m³')

                    carregamento = Carregamento(
                        volumes=volumes,
                        evento_conclusao=env.event(),
                    )
                    yield self._store_eventos_carregamento.put(carregamento)
                    yield carregamento.evento_conclusao
                else:
                    log(f'recusa carregamento, irá terminar às {dt_fim_carga.format('HH:mm')}')

    def _executa_funcionarios__descarga(
            self,
            env: simpy.Environment,
            volumes: list[float],
            qtd_funcionarios: int = 6,
    ) -> sd.Generator:
        log = functools.partial(self._log, env, f'equipe({qtd_funcionarios})')
        volumes_funcionario = [list(arr) for arr in np.array_split(volumes, qtd_funcionarios)]
        log(f'inicia descarregamento de caixas: ({[len(v) for v in volumes_funcionario]})')
        yield simpy.events.AllOf(env, [
            env.process(self._processa_funcionario__descarga(env, volumes))
            for volumes in volumes_funcionario
        ])

        # Colocam no depósito
        for volume in volumes:
            yield self._container_deposito.put(volume)
            yield self._store_deposito.put(volume)
        log(f'coloca {len(volumes)} caixas no depósito')

        self._evento_finalizar_descarga.succeed()
        self._evento_iniciar_descarga = env.event()
        self._evento_finalizar_descarga = env.event()

    def _executa_funcionarios__carga(
            self,
            env: simpy.Environment,
            volumes: list[float],
            qtd_funcionarios: int = 6,
    ) -> sd.Generator:
        volumes_funcionario = [list(arr) for arr in np.array_split(volumes, qtd_funcionarios)]
        self._log(env,
                  f"equipe({qtd_funcionarios}): inicia carregamento de caixas ({[len(v) for v in volumes_funcionario]})")
        yield simpy.events.AllOf(env, [
            env.process(self._processa_funcionario__carga(env, volumes))
            for volumes in volumes_funcionario
        ])
        self._evento_finalizar_carga.succeed()
        self._evento_iniciar_carga = env.event()
        self._evento_finalizar_carga = env.event()

    def _processa_funcionarios__carregamento(self, env: simpy.Environment):
        while True:
            # Aguarda ter algum evento de carga ou descarga
            eventos = yield self._evento_iniciar_carga | self._evento_iniciar_descarga
            match dict(eventos):
                # Caso ocorra um evento apenas de descarga
                case {self._evento_iniciar_descarga: volumes_descarga}:
                    yield env.process(self._executa_funcionarios__descarga(env, volumes_descarga, 6))

                # Caso ocorra um evento apenas de carga
                case {self._evento_iniciar_carga: volumes_carga}:
                    yield env.process(self._executa_funcionarios__carga(env, volumes_carga, 6))

                # Caso ocorra um evento de descarga e de carga ao mesmo tempo
                case {self._evento_iniciar_descarga: volumes_descarga, self._evento_iniciar_carga: volumes_carga}:
                    self._log(env, "equipe: carrega/descarrega caixas")
                    yield simpy.AllOf(env, [
                        env.process(self._executa_funcionarios__descarga(env, volumes_descarga, 4)),
                        env.process(self._executa_funcionarios__carga(env, volumes_carga, 2)),
                    ])

    def _processa_funcionario__descarga(self, env: simpy.Environment, volumes: list[float]) -> sd.Generator:
        for _ in volumes:
            # Um funcionário é capaz de descarregar 12 caixas
            # (independente do volume) por hora do caminhão
            yield env.timeout(1 / self._velocidade_descarga)

    def _processa_funcionario__carga(self, env: simpy.Environment, volumes: list[float]) -> sd.Generator:
        # Um funcionário é capaz de carregar 20 caixas por hora na van
        yield env.timeout(len(volumes) / self._velocidade_carga)

    _evento_iniciar_carregamento: simpy.Event

    @typing.override
    def _log(self, env: simpy.Environment, *args: str) -> None:
        if self._deve_exibir_log:
            now = env.now
            dia = int(now / 24) + 1
            dt = arrow.get(datetime.datetime.now().date()).shift(hours=now % 24)
            print(f'dia {dia}', dt.format('HH[h]mm'), *args, sep=': ')

    def _processa_van(self, env: simpy.Environment, van: Van) -> sd.Generator:
        log = functools.partial(self._log, env, f'van {van.id}')
        while True:
            with self._resource_carga_vans.request() as request_carga:
                # (Fila) Aguarda ponto de carga estar desocupado
                tempo_inicial_area_carga = env.now
                yield request_carga
                self._estatisticas.tempos_espera_area_carga.append(env.now - tempo_inicial_area_carga)

                # [Atividade] Ocupa ponto de carga
                log('ocupa ponto de carga')
                yield env.timeout(0)

                log('aguarda itens o suficiente para iniciar carregamento')
                # (Fila) Aguarda itens o suficiente para serem carregados
                tempo_inicial_espera_carregar = env.now
                carregamento: Carregamento = yield self._store_eventos_carregamento.get()
                self._estatisticas.tempos_espera_carregar.append(env.now - tempo_inicial_espera_carregar)

                # [Atividade] Ocupa itens a serem carregados

                # (Fila) Aguarda funcionários carregarem
                log('aguarda equipe carregar')
                self._evento_iniciar_carga.succeed(value=carregamento.volumes)
                tempo_inicial_carregar = env.now
                yield self._evento_finalizar_carga
                self._estatisticas.tempos_carregar.append(env.now - tempo_inicial_carregar)

                carregamento.evento_conclusao.succeed()

            # [Atividade] Van realiza entrega
            # A van passa em média 4 horas, com distribuição normal e desvio
            # de 1 hora, para finalizar as entregas aos destinatários
            log('sai para a entrega')
            yield env.timeout(abs(self._rnd.normal(loc=4, scale=1)))
            log('chega da entrega')

    def _processa_caminhao(self, env: simpy.Environment) -> sd.Generator:
        log = functools.partial(self._log, env, 'caminhão')
        while True:
            volumes: list[float] = []
            while True:
                # O volume das encomendas varia de acordo com uma função de probabilidade
                # triangular com no mínimo 0,03m³, volume mais provável 0,12m³ e volume máximo de 1m³
                volume = self._rnd.triangular(left=0.03, mode=0.12, right=1)

                # Um caminhão tem a capacidade máxima de 20m³, mas
                # não vem necessariamente na capacidade total
                if sum(volumes) + volume > self._tamanho_caminhao:
                    break

                volumes.append(volume)

            # Chegam caminhões em média a cada 15h segundo uma
            # distribuição exponencial (a qualquer hora do dia)
            yield env.timeout(self._rnd.exponential(scale=15))

            log(f'chega no centro com {len(volumes)} caixas, total {sum(volumes):.2f} m³')
            with self._resource_estacionamento_caminhoes.request() as request_estacionamento:
                tempo_inicial_caminhao_espera_vaga = env.now
                # (Fila) Aguarda vaga no estacionamento
                yield request_estacionamento
                self._estatisticas.tempos_espera_estacionar.append(env.now - tempo_inicial_caminhao_espera_vaga)

                # [Atividade] Estaciona
                yield env.timeout(0)  # TODO Adicionar como demanda ausente
                log('estaciona')

                # (Fila) Aguarda centro de distribuição abrir
                tempo_aguardo_abertura: int
                hora_atual = env.now % 24
                # Se o caminhão chega antes do centro ter aberto (ex.: 03AM)
                if hora_atual < self._hora_inicio_funcionamento:
                    # Aguarda o tempo restante para o centro abrir (ex.: 08AM - 03AM = 4 horas)
                    tempo_aguardo_abertura = self._hora_inicio_funcionamento - hora_atual
                # Se o caminhão chega depois do centro ter fechado (ex.: 06PM)
                elif hora_atual > self._hora_final_funcionamento:
                    # Aguarda o tempo restante para o centro abrir (ex.: 08AM - 00AM = 8 horas)
                    tempo_aguardo_abertura = 24 - hora_atual + self._hora_inicio_funcionamento
                else:
                    tempo_aguardo_abertura = 0

                if tempo_aguardo_abertura > 0:
                    log(f'aguarda ~{tempo_aguardo_abertura:.0f}h para descarregar')
                tempo_inicial_caminhao_espera_abertura = env.now
                yield env.timeout(tempo_aguardo_abertura)
                self._estatisticas.tempos_espera_abertura.append(env.now - tempo_inicial_caminhao_espera_abertura)

                # [Atividade] Libera descarregamento
                yield env.timeout(0)  # TODO Adicionar como demanda ausente

                log('aguarda vaga para descarregar')
                with self._resource_descarga_caminhoes.request() as request_descarga:
                    # (Fila) Aguarda área de descarga
                    tempo_inicial_caminhao_espera_area = env.now
                    yield request_descarga
                    self._estatisticas.tempos_espera_descarregar.append(env.now - tempo_inicial_caminhao_espera_area)

                    # [Atividade] Ocupa área de descarga
                    yield env.timeout(0)

                    log('aguarda equipe descarregar')
                    self._evento_iniciar_descarga.succeed(value=volumes)
                    # (Fila) Aguarda funcionários descarregarem

                    tempo_inicial_descarregar_caminhao = env.now
                    yield self._evento_finalizar_descarga
                    self._estatisticas.tempos_descarregar.append(
                        env.now - tempo_inicial_descarregar_caminhao)


class ExecutorCentroDistribuicao(sd.ExecutorModelo[_Metrica]):
    def inicializa_modelo(
            self,
            dados_modelos: dict[str, dict[str, typing.Any]],
            seed: int | None,
            deve_exibir_log: bool,
    ) -> Modelo[_Metrica]:
        dados_modelo = dados_modelos.get('centro-distribuicao', {})
        qtd_max_caminhoes = dados_modelo.get('qtd-caminhoes', 5)
        qtd_vans = dados_modelo.get('qtd-vans', 4)
        qtd_funcionarios = dados_modelo.get('qtd-funcionarios', 6)
        tamanho_caminhao = dados_modelo.get('tamanho-caminhao', 20)
        tamanho_van = dados_modelo.get('tamanho-van', 8)
        tamanho_deposito = dados_modelo.get('tamanho-deposito', 300)
        velocidade_descarga = dados_modelo.get('velocidade-descarga', 12)
        velocidade_carga = dados_modelo.get('velocidade-carga', 20)
        return ModeloCentroDistribuicao(
            seed=seed,
            deve_exibir_log=deve_exibir_log,
            qtd_max_caminhoes=qtd_max_caminhoes,
            qtd_vans=qtd_vans,
            qtd_funcionarios=qtd_funcionarios,
            tamanho_caminhao=tamanho_caminhao,
            tamanho_van=tamanho_van,
            tamanho_deposito=tamanho_deposito,
            velocidade_carga=velocidade_carga,
            velocidade_descarga=velocidade_descarga,
        )

    def lista_metricas(self) -> typing.Sequence[_Metrica]:
        return list(_Metrica)

    def exibe_modelo_executado(self, modelo: Modelo[_Metrica]) -> None:
        for metrica in self.lista_metricas():
            valores = modelo.calcula_metrica(metrica)
            if metrica == _Metrica.TEMPO_DESCARREGAR:
                print(f'Número de caminhões: {len(valores)}')
            elif metrica == _Metrica.TEMPO_CARREGAR:
                print(f'Número de entregas: {len(valores)}')
            label = self.descreve_metrica(metrica)
            self._log_stats(label, valores)

    def descreve_metrica(self, metrica: _Metrica) -> str:
        match metrica:
            case _Metrica.TEMPO_ESPERA_ESTACIONAR:
                return 'Espera p/ estacionar (caminhão)'
            case _Metrica.TEMPO_ESPERA_ABERTURA:
                return 'Espera p/ abrir (caminhão)'
            case _Metrica.TEMPO_ESPERA_DESCARREGAR:
                return 'Espera p/ área de descarga (caminhão)'
            case _Metrica.TEMPO_DESCARREGAR:
                return 'Descarregar (caminhão)'
            case _Metrica.TEMPO_ESPERA_AREA_CARGA:
                return 'Espera p/ área de carga (van)'
            case _Metrica.TEMPO_ESPERA_CARREGAR:
                return 'Espera p/ carregar (van)'
            case _Metrica.TEMPO_CARREGAR:
                return 'Carregar (van)'
            case _:
                typing.assert_never(metrica)


def main() -> None:
    executor = ExecutorCentroDistribuicao()
    sd.executa_script(
        executor,
        x_range=(1 * 24, 5 * 24, 12),
        y_range=(0, 5, 1),
        time_unit='hours',
    )


if __name__ == '__main__':
    main()
