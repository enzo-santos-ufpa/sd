import dataclasses
import functools
import itertools
import os
import statistics
import tomllib
import typing

import arrow.locales
import numpy.random
import simpy
import simpy.resources.resource
from matplotlib import pyplot as plt


@dataclasses.dataclass
class Copo:
    id: int
    limpo: bool


@dataclasses.dataclass
class Coleta:
    id_pedido: int
    id_cliente: int
    evento_conclusao: simpy.Event


@dataclasses.dataclass
class Preparo:
    copo: Copo | None
    evento_conclusao: simpy.Event


@dataclasses.dataclass
class Funcionario:
    id: int


@dataclasses.dataclass
class Estatisticas:
    no_pedidos_consumidos: int
    tempos_estadia_cliente: list[float]
    tempos_espera_sentar_cliente: list[float]
    tempos_espera_pedir_cliente: list[float]
    tempos_espera_consumir_cliente: list[float]
    tempos_preparo: list[float]


class ModeloBarExpresso:
    _rnd: numpy.random.Generator
    _deve_exibir_log: bool
    _estatisticas: Estatisticas
    _qtd_funcionarios: int
    _qtd_copos: int
    _qtd_cadeiras: int
    _qtd_copos_pia: int

    _env: simpy.Environment
    _store_funcionarios: simpy.Store
    _store_copos: simpy.Store
    _resource_cadeiras: simpy.Resource
    _resource_lavagem: simpy.Resource

    @property
    def estatisticas(self) -> Estatisticas:
        return self._estatisticas

    def __init__(
            self,
            *,
            seed: int | None,
            qtd_funcionarios: int,
            qtd_cadeiras: int,
            qtd_copos: int,
            qtd_copos_pia: int,
            deve_exibir_log: bool = False,
    ):
        self._qtd_funcionarios = qtd_funcionarios
        self._qtd_cadeiras = qtd_cadeiras
        self._qtd_copos = qtd_copos
        self._qtd_copos_pia = qtd_copos_pia
        self._deve_exibir_log = deve_exibir_log

        self._rnd = numpy.random.default_rng(seed)
        self._estatisticas = Estatisticas(
            no_pedidos_consumidos=0,
            tempos_estadia_cliente=[],
            tempos_espera_sentar_cliente=[],
            tempos_espera_pedir_cliente=[],
            tempos_espera_consumir_cliente=[],
            tempos_preparo=[],
        )

    def inicia(self, env: simpy.Environment) -> None:
        # O bar possui 2 funcionários
        self._store_funcionarios = simpy.Store(env, capacity=self._qtd_funcionarios)
        for idx_funcionario in range(self._qtd_funcionarios):
            self._store_funcionarios.put(Funcionario(id=idx_funcionario + 1))

        # O bar possui 20 copos
        self._store_copos = simpy.Store(env, capacity=self._qtd_copos)
        for idx_copo in range(self._qtd_copos):
            self._store_copos.put(Copo(id=idx_copo + 1, limpo=True))

        # O bar possui um balcão com 6 cadeiras
        self._resource_cadeiras = simpy.Resource(env, capacity=self._qtd_cadeiras)
        # Como a pia é pequena, só pode ficar 6 copos sujos no máximo
        self._resource_lavagem = simpy.Resource(env, capacity=self._qtd_copos_pia)

        self._eventos_preparo = simpy.Store(env)
        self._eventos_coleta = simpy.Store(env)
        env.process(self._processa_clientes(env))
        env.process(self._processa_funcionario__preparo(env))
        env.process(self._processa_funcionario__coleta(env))

    def _log(self, env: simpy.Environment, *args: str):
        if self._deve_exibir_log:
            print(f'{env.now:05.2f}', *args, sep=': ')

    _eventos_preparo: simpy.Store
    _eventos_coleta: simpy.Store

    def _processa_clientes(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        for id_cliente in itertools.count(start=1):
            env.process(self._processa_cliente(env, id_cliente))

            # Os clientes chegam em média a cada 4 min
            # de acordo com uma função exponencial
            yield env.timeout(self._rnd.exponential(4))

    def _processa_cliente(self, env: simpy.Environment, id_cliente: int) -> typing.Generator[simpy.Event, None, None]:
        log = functools.partial(self._log, env, f'cliente {id_cliente}')
        log('chega')
        tempo_inicio_estadia = env.now

        copo: Copo | None = None

        tempo_inicio_espera_sentar = env.now
        with self._resource_cadeiras.request() as request_cadeira:
            # (Fila) Aguarda cadeira
            yield request_cadeira

            # [Atividade] Ocupa cadeira
            self._estatisticas.tempos_espera_sentar_cliente.append(env.now - tempo_inicio_espera_sentar)

            # A probabilidade de um cliente tomar 1 copo é de 0,3; 2 copos 0,45; 3 copos 0,2; e 4 copos 0,05.
            qtd_pedidos = self._rnd.choice([1, 2, 3, 4], p=[0.3, 0.45, 0.2, 0.05])
            log(f'ocupa cadeira e pretende consumir {qtd_pedidos} pedidos')

            for idx_pedido in range(qtd_pedidos):
                # (Fila) Aguarda funcionário ficar disponível para coletar o pedido
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'aguarda funcionário ficar disponível')
                tempo_inicio_espera_pedir = env.now

                evento_coleta = env.event()
                yield self._eventos_coleta.put(evento_coleta)  # Coloca um evento na fila de coleta do funcionário

                evento_conclusao_coleta = env.event()
                evento_coleta.succeed(
                    value=Coleta(
                        id_pedido=idx_pedido + 1,
                        id_cliente=id_cliente,
                        evento_conclusao=evento_conclusao_coleta,
                    )
                )
                yield evento_conclusao_coleta  # Aguarda até que o evento seja concluído pelo funcionário
                self._estatisticas.tempos_espera_pedir_cliente.append(env.now - tempo_inicio_espera_pedir)

                tempo_inicio_espera_consumir = env.now
                # (Fila) Aguarda pedido ficar pronto
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'aguarda pedido ser preparado')

                evento_preparo = env.event()
                yield self._eventos_preparo.put(evento_preparo)  # Coloca um evento na fila de preparo do funcionário

                evento_conclusao_preparo = env.event()
                evento_preparo.succeed(
                    value=Preparo(copo=copo, evento_conclusao=evento_conclusao_preparo),
                )
                copo: Copo = yield evento_conclusao_preparo  # Aguarda até que o evento seja concluído pelo funcionário
                self._estatisticas.tempos_espera_consumir_cliente.append(env.now - tempo_inicio_espera_consumir)

                # [Atividade] Consume pedido
                # Os clientes levam em média 3 min para consumir uma bebida de acordo
                # com uma função normal com desvio padrão de 1min
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'consome pedido')
                yield env.timeout(abs(self._rnd.normal(3, scale=1)))

                self._estatisticas.no_pedidos_consumidos += 1

        if copo is not None:
            yield self._store_copos.put(copo)

        self._estatisticas.tempos_estadia_cliente.append(env.now - tempo_inicio_estadia)

    def _processa_funcionario__coleta(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            # Aguarda um evento ser colocado na fila de coleta
            evento_coleta = yield self._eventos_coleta.get()
            coleta: Coleta = yield evento_coleta

            # (Fila) Aguarda funcionário
            funcionario: Funcionario = yield self._store_funcionarios.get()
            log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

            # [Atividade] Coleta do pedido
            # Funcionários atendem o pedido em 0,7min com desvio de 0,3min
            log(f'coleta pedido {coleta.id_pedido} do cliente {coleta.id_cliente}')
            yield env.timeout(abs(self._rnd.normal(0.7, scale=0.3)))

            yield self._store_funcionarios.put(funcionario)

            coleta.evento_conclusao.succeed()

    def _processa_funcionario__preparo(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            # Aguarda um evento ser colocado na fila de preparo
            evento_preparo = yield self._eventos_preparo.get()
            preparo: Preparo = yield evento_preparo

            # (Fila) Aguarda funcionário
            funcionario: Funcionario = yield self._store_funcionarios.get()
            log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

            # [Atividade] Ocupa funcionário

            tempo_inicial_preparo = env.now

            copo: Copo
            # Se o cliente ainda não possuir um copo
            if preparo.copo is None:
                # (Fila) Aguarda copo
                novo_copo = yield self._store_copos.get()

                # [Atividade] Ocupa copo
                log('ocupa copo')
                copo = novo_copo

            # Copo reutilizado do último pedido do cliente
            else:
                copo = preparo.copo

            if not copo.limpo:
                with self._resource_lavagem.request() as request_lavagem:
                    # (Fila) Aguarda pia
                    yield request_lavagem

                    # [Atividade] Lava copo
                    yield env.timeout(0)
                    log('lava copo')

                copo.limpo = True

            # (Fila) Aguarda freezer ficar disponível
            yield env.timeout(0)  # delay=0, pois o freezer sempre está disponível

            # [Atividade] Coloca no freezer
            # Funcionários lavam o copo e colocam no freezer em 0,5min com desvio de 0,1min
            yield env.timeout(self._rnd.normal(0.5, scale=0.1))
            log('coloca copo no freezer')

            # Desocupa funcionário
            yield self._store_funcionarios.put(funcionario)

            # (Fila) Aguarda copo congelar
            # O copo deve ficar no freezer por 4min antes de ser usado para servir
            log('aguarda copo congelar')
            yield env.timeout(4)

            self._estatisticas.tempos_preparo.append(env.now - tempo_inicial_preparo)

            log('retira copo do freezer')
            preparo.evento_conclusao.succeed(value=copo)


def main() -> None:
    try:
        with open(os.path.join(os.path.dirname(os.getcwd()), 'config.toml'), 'rb') as f:
            dados = tomllib.load(f)
    except FileNotFoundError:
        dados = {}

    dados_geral = dados.get('geral', {})
    seed = dados_geral.get('seed')

    dados_modelos = dados.get('modelos', {})
    dados_modelo = dados_modelos.get('bar-expresso', {})
    qtd_cadeiras = dados_modelo.get('qtd-cadeiras', 6)
    qtd_funcionarios = dados_modelo.get('qtd-funcionarios', 2)
    qtd_copos = dados_modelo.get('qtd-copos', 20)
    qtd_copos_pia = dados_modelo.get('qtd-copos-pia', 6)

    dados_grafico = dados.get('grafico', {})
    deve_exibir_grafico = dados_grafico.get('exibir', False)
    if not deve_exibir_grafico:
        env = simpy.Environment()
        modelo = ModeloBarExpresso(
            seed=seed,
            qtd_cadeiras=qtd_cadeiras,
            qtd_funcionarios=qtd_funcionarios,
            qtd_copos=qtd_copos,
            qtd_copos_pia=qtd_copos_pia,
            deve_exibir_log=True,
        )
        modelo.inicia(env)
        env.run(until=70)

        print(f'Número de clientes: {len(modelo.estatisticas.tempos_estadia_cliente)}')
        print(f'Número de pedidos: {len(modelo.estatisticas.tempos_espera_consumir_cliente)}')
        log_stats('Tempo estadia (por cliente)', modelo.estatisticas.tempos_estadia_cliente)
        log_stats('Tempo espera p/ sentar (por cliente)', modelo.estatisticas.tempos_espera_sentar_cliente)
        log_stats('Tempo espera p/ pedir (por pedido)', modelo.estatisticas.tempos_espera_pedir_cliente)
        log_stats('Tempo espera p/ consumir (por pedido)', modelo.estatisticas.tempos_espera_consumir_cliente)
        log_stats('Tempo preparo (por pedido)', modelo.estatisticas.tempos_preparo)
        return

    x = []
    y0 = []
    y1 = []
    y2 = []
    y3 = []
    y4 = []
    for until in range(30, 360 + 1, 30):
        env = simpy.Environment()
        modelo = ModeloBarExpresso(
            seed=seed,
            qtd_cadeiras=qtd_cadeiras,
            qtd_funcionarios=qtd_funcionarios,
            qtd_copos=qtd_copos,
            qtd_copos_pia=qtd_copos_pia,
            deve_exibir_log=False,
        )
        modelo.inicia(env)
        env.run(until=until)

        x.append(until)
        y0.append(statistics.mean(modelo.estatisticas.tempos_estadia_cliente))
        y1.append(statistics.mean(modelo.estatisticas.tempos_espera_sentar_cliente))
        y2.append(statistics.mean(modelo.estatisticas.tempos_espera_pedir_cliente))
        y3.append(statistics.mean(modelo.estatisticas.tempos_espera_consumir_cliente))
        y4.append(statistics.mean(modelo.estatisticas.tempos_preparo))

    fig, ax = plt.subplots()
    ax.plot(x, y0, label='Estadia')
    ax.plot(x, y1, label='Espera p/ sentar')
    ax.plot(x, y2, label='Espera p/ pedir')
    ax.plot(x, y3, label='Espera p/ consumir')
    ax.plot(x, y4, label='Preparo')
    ax.set_xlabel('Tempo da simulação (min)')
    ax.set_ylabel('Tempo médio da ação (min)')
    ax.set_xlim(30, 360)
    ax.set_ylim(0, 120)
    ax.set_xticks(list(range(30, 360 + 1, 30)))
    ax.set_yticks(list(range(0, 120 + 1, 15)))
    ax.legend()
    plt.show()


def log_stats(prefix: str, values: list[float]) -> None:
    def fmt(delta: float) -> str:
        dt = arrow.utcnow().shift(minutes=delta)
        return dt.humanize(locale='pt', only_distance=True, granularity=['hour', 'minute', 'second'])

    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    print(f'{prefix}: {fmt(mean)} (± {stdev:.2f}), min={fmt(min(values))}, max={fmt(max(values))}')


if __name__ == '__main__':
    main()
