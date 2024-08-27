import itertools
import random
import typing

import numpy as np
import numpy.random
import simpy


def generate_random_integers(n, x):
    if n == 1:
        return [x]

    # Generate n-1 random boundaries between 0 and x
    boundaries = sorted(random.randint(0, x) for _ in range(n - 1))

    # Calculate the differences between the boundaries
    random_integers = [boundaries[0]] + \
                      [boundaries[i] - boundaries[i - 1] for i in range(1, n - 1)] + \
                      [x - boundaries[-1]]

    return random_integers


class ModeloCentroDistribuicao:
    _hora_inicio_funcionamento: int
    # A empresa funciona 8h por dia para carga e descarga
    _duracao_funcionamento: typing.Final[int] = 8

    @property
    def _hora_final_funcionamento(self):
        return self._hora_inicio_funcionamento + self._duracao_funcionamento

    _should_log: bool
    _rnd: numpy.random.Generator
    _resource_descarga_caminhoes: simpy.Resource
    _resource_estacionamento_caminhoes: simpy.Resource
    _resource_carga_vans: simpy.Resource

    _store_deposito: simpy.Store
    _container_deposito: simpy.Container

    _evento_carga: simpy.Event
    _evento_descarga: simpy.Event
    _evento_carga_ok: simpy.Event
    _evento_descarga_ok: simpy.Event

    def __init__(self, should_log: bool = False) -> None:
        self._rnd = numpy.random.default_rng(1)
        self._hora_inicio_funcionamento = 8  # 08AM

        self._should_log = should_log

    def _log(self, env: simpy.Environment, message: str) -> None:
        if self._should_log:
            print(f'{env.now:05.2f}: {message}')

    def executa(self, env: simpy.Environment) -> None:
        # O depósito pode armazenar 300m³
        self._store_deposito = simpy.Store(env)
        self._container_deposito = simpy.Container(env, capacity=300)

        # Só existe um ponto de descarga de caminhões
        self._resource_descarga_caminhoes = simpy.Resource(env, capacity=1)
        # e um pátio para estacionar 5 caminhões
        self._resource_estacionamento_caminhoes = simpy.Resource(env, capacity=5)

        # Existe um outro ponto para carga de uma van
        self._resource_carga_vans = simpy.Resource(env, capacity=1)

        self._evento_carga = env.event()
        self._evento_descarga = env.event()
        self._evento_carga_ok = env.event()
        self._evento_descarga_ok = env.event()

        env.process(self._executa_funcionarios(env))
        env.process(self._executa_caminhao(env))
        env.process(self._executa_van(env))

    def _executa_funcionarios(self, env: simpy.Environment):
        while True:
            # Aguarda ter algum evento de carga ou descarga
            eventos = yield self._evento_carga | self._evento_descarga
            match dict(eventos):
                case {self._evento_descarga: volumes_descarga}:
                    volumes_funcionario = [list(arr) for arr in np.array_split(volumes_descarga, 6)]
                    self._log(env, f"equipe: descarrega caixas ({[len(v) for v in volumes_funcionario]})")
                    yield simpy.events.AllOf(env, [
                        env.process(self._emite_descarregamento(env, volumes))
                        for volumes in volumes_funcionario
                    ])
                    self._evento_descarga_ok.succeed()
                    self._evento_descarga = env.event()
                    self._evento_descarga_ok = env.event()

                case {self._evento_carga: volumes_carga}:
                    volumes_funcionario = [list(arr) for arr in np.array_split(volumes_carga, 6)]
                    self._log(env, f"equipe: carrega caixas ({[len(v) for v in volumes_funcionario]})")
                    yield simpy.events.AllOf(env, [
                        env.process(self._emite_carregamento(env, volumes))
                        for volumes in volumes_funcionario
                    ])
                    self._evento_carga_ok.succeed()
                    self._evento_carga = env.event()
                    self._evento_carga_ok = env.event()

                # Por padrão, quando há caminhão e van para serem processados
                # ao mesmo tempo, trabalham 4 no caminhão e 2 na van
                case {self._evento_carga: volumes_carga, self._evento_descarga: volumes_descarga}:
                    self._log(env, "equipe: carrega/descarrega caixas")

                    # Caminhão: 4 funcionários
                    volumes_funcionario = [list(arr) for arr in np.array_split(volumes_descarga, 4)]
                    yield simpy.events.AllOf(env, [
                        env.process(self._emite_descarregamento(env, volumes))
                        for volumes in volumes_funcionario
                    ])
                    self._evento_descarga_ok.succeed()
                    self._evento_descarga = env.event()
                    self._evento_descarga_ok = env.event()

                    # Van: 2 funcionários
                    volumes_funcionario = [list(arr) for arr in np.array_split(volumes_carga, 2)]
                    yield simpy.events.AllOf(env, [
                        env.process(self._emite_carregamento(env, volumes))
                        for volumes in volumes_funcionario
                    ])
                    self._evento_carga_ok.succeed()
                    self._evento_carga = env.event()
                    self._evento_carga_ok = env.event()

    @staticmethod
    def _emite_descarregamento(
            env: simpy.Environment,
            volumes: list[float],
    ) -> typing.Generator[simpy.Event, None, None]:
        for _ in volumes:
            # Um funcionário é capaz de descarregar 12 caixas
            # (independente do volume) por hora do caminhão
            yield env.timeout(1 / 12)

    @staticmethod
    def _emite_carregamento(
            env: simpy.Environment,
            volumes: list[float],
    ) -> typing.Generator[simpy.Event, None, None]:
        for _ in volumes:
            # Um funcionário é capaz de carregar 20 caixas por hora na van
            yield env.timeout(1 / 20)

    def _executa_van(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            self._log(env, 'van: aguarda vaga para carregar')

            # (Fila) Aguarda carregamento
            with self._resource_carga_vans.request() as request_carga:
                yield request_carga

                # [Atividade] Inicia carregamento
                volume_maximo = 8  # As vans têm capacidade de 8m³
                volumes: list[float] = []
                for idx_volume in itertools.count(start=0):
                    volume = yield self._store_deposito.get()
                    yield self._container_deposito.get(volume)

                    # Se a próxima caixa a ser carregada exceder o volume máximo da van,
                    if sum(volumes) + volume > volume_maximo:
                        # encerre o carregamento
                        break

                    # Caso não exceda, carregue esta caixa
                    volumes.append(volume)
                    self._log(env, f'van: recebe volume {idx_volume + 1}: {volume:.2f}/{sum(volumes):.5f} m³')

                # (Fila) Aguarda funcionários carregarem
                self._log(env, 'van: aguarda equipe carregar')
                self._evento_carga.succeed(value=volumes)
                yield self._evento_carga_ok

            # [Atividade] Van realiza entrega
            # A van passa em média 4 horas, com distribuição normal e desvio
            # de 1 hora, para finalizar as entregas aos destinatários
            self._log(env, 'van: sai para a entrega')
            yield env.timeout(self._rnd.normal(loc=4, scale=1))

    def _executa_caminhao(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            # Chegam caminhões em média a cada 15h segundo uma
            # distribuição exponencial (a qualquer hora do dia)
            yield env.timeout(self._rnd.exponential(scale=15))

            volumes: list[float] = []
            while True:
                # O volume das encomendas varia de acordo com uma função de probabilidade
                # triangular com no mínimo 0,03m³, volume mais provável 0,12m³ e volume máximo de 1m³
                volume = self._rnd.triangular(left=0.03, mode=0.12, right=1)

                # Um caminhão tem a capacidade máxima de 20m³, mas
                # não vem necessariamente na capacidade total
                if sum(volumes) + volume > 20:
                    break

                volumes.append(volume)

            self._log(env, f'caminhão: chega no centro com {len(volumes)} caixas, total {sum(volumes):.2f} m³')

            # (Fila) Estacionamento
            with self._resource_estacionamento_caminhoes.request() as request_estacionamento:
                yield request_estacionamento

                # [Atividade] Estaciona
                yield env.timeout(0)
                self._log(env, f'caminhão: estaciona')

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
                    self._log(env, f'caminhão: aguarda {tempo_aguardo_abertura:.0f}h para descarregar')
                yield env.timeout(tempo_aguardo_abertura)

                self._log(env, 'caminhão: aguarda vaga para descarregar')
                # (Fila) Aguarda descarregamento
                with self._resource_descarga_caminhoes.request() as request_descarga:
                    yield request_descarga

                    # [Atividade] Inicia descarregamento
                    yield env.timeout(0)

                    self._log(env, 'caminhão: aguarda equipe descarregar')
                    self._evento_descarga.succeed(value=volumes)
                    # (Fila) Aguarda funcionários carregarem
                    yield self._evento_descarga_ok

                    # Coloca no depósito
                    for volume in volumes:
                        yield self._container_deposito.put(volume)
                        yield self._store_deposito.put(volume)


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloCentroDistribuicao(should_log=True)
    modelo.executa(env)
    env.run(until=24 * 10)


if __name__ == '__main__':
    main()
