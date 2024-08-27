import itertools
import typing

import numpy.random
import simpy
import simpy.resources.resource


class ModeloBarExpresso:
    _env: simpy.Environment
    _rnd: numpy.random.Generator
    _resource_funcionarios: simpy.Resource
    _resource_copos: simpy.Resource
    _resource_cadeiras: simpy.Resource
    _resource_pia: simpy.Resource

    def __init__(self):
        self._rnd = numpy.random.default_rng(42)

    def inicia(self, env: simpy.Environment) -> None:
        # O bar possui 2 funcionários
        self._resource_funcionarios = simpy.Resource(env, capacity=2)
        # O bar possui 20 copos
        self._resource_copos = simpy.Resource(env, capacity=20)
        # O bar possui um balcão com 6 cadeiras
        self._resource_cadeiras = simpy.Resource(env, capacity=6)
        # Como a pia é pequena, só pode ficar 6 copos sujos no máximo
        self._resource_pia = simpy.Resource(env, capacity=6)

        self._eventos_atendimento = simpy.Store(env)
        env.process(self._processa_clientes(env))
        env.process(self._processa_atendimento(env))

    def _log(self, env: simpy.Environment, *args: str):
        if True:
            print(f'{env.now:05.2f}', *args, sep=': ')

    _eventos_atendimento: simpy.Store

    def _processa_clientes(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        for id_cliente in itertools.count(start=1):
            env.process(self._processa_cliente(env, id_cliente))

            # Os clientes chegam em média a cada 4 min
            # de acordo com uma função exponencial
            yield env.timeout(self._rnd.exponential(4))

    def _processa_cliente(self, env: simpy.Environment, id_cliente: int) -> typing.Generator[simpy.Event, None, None]:
        self._log(env, f'cliente {id_cliente}', 'chega')
        with self._resource_cadeiras.request() as request_cadeira:
            # (Fila) Aguarda cadeira
            yield request_cadeira

            # [Atividade] Ocupa cadeira
            self._log(env, f'cliente {id_cliente}', 'ocupa cadeira')

            # A probabilidade de um cliente tomar 1 copo é de 0,3; 2 copos 0,45; 3 copos 0,2; e 4 copos 0,05.
            qtd_pedidos = self._rnd.choice([1, 2, 3, 4], p=[0.3, 0.45, 0.2, 0.05])
            for idx_pedido in range(qtd_pedidos):
                with self._resource_funcionarios.request() as request_funcionario:
                    # (Fila) Aguarda funcionário
                    yield request_funcionario

                    # [Atividade] Coleta do pedido
                    # Funcionários atendem o pedido em 0,7min com desvio de 0,3min
                    self._log(env, f'cliente {id_cliente}', f'pedido {idx_pedido + 1}/{qtd_pedidos}',
                              'informa pedido ao funcionário')
                    yield env.timeout(self._rnd.normal(0.7, scale=0.3))

                with self._resource_copos.request() as request_copo:
                    yield request_copo
                    # (Fila) Aguarda copo
                    self._log(env, f'cliente {id_cliente}', f'pedido {idx_pedido + 1}/{qtd_pedidos}',
                              'aguarda copo')

                    # [Atividade] Ocupa copo

                    # (Fila) Aguarda pedido
                    self._log(env, f'cliente {id_cliente}', f'pedido {idx_pedido + 1}/{qtd_pedidos}',
                              'aguarda pedido')

                    evento_atendimento = env.event()
                    yield self._eventos_atendimento.put(evento_atendimento)

                    evento_atendimento_ok = env.event()
                    evento_atendimento.succeed(value=evento_atendimento_ok)
                    yield evento_atendimento_ok

                    # [Atividade] Consume pedido
                    # Os clientes levam em média 3 min para consumir uma bebida de acordo
                    # com uma função normal com desvio padrão de 1min
                    self._log(env, f'cliente {id_cliente}', f'pedido {idx_pedido + 1}/{qtd_pedidos}',
                              'consome pedido')
                    yield env.timeout(self._rnd.normal(3, scale=1))

    def _processa_atendimento(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            evento_processamento = yield self._eventos_atendimento.get()
            evento_processamento_ok = yield evento_processamento

            with self._resource_funcionarios.request() as request_funcionario:
                yield request_funcionario

                # [Atividade] Ocupa funcionário
                self._log(env, 'funcionário', 'inicia preparo')

                with self._resource_pia.request() as request_pia:
                    yield request_pia
                    # (Fila) Aguarda pia

                    # [Atividade] Lava copo
                    yield env.timeout(0)
                    self._log(env, 'funcionário', 'lava copo')

                # (Fila) Aguarda espaço no freezer
                yield env.timeout(0)

                # [Atividade] Coloca no freezer
                # Funcionários lavam o copo e colocam no freezer em 0,5min com desvio de 0,1min
                yield env.timeout(self._rnd.normal(0.5, scale=0.1))
                self._log(env, 'funcionário', 'coloca no freezer')

            # (Fila) Aguarda copo congelar
            # O copo deve ficar no freezer por 4min antes de ser usado para servir
            self._log(env, 'funcionário', 'aguarda copo congelar')
            yield env.timeout(4)

            self._log(env, 'funcionário', 'finaliza preparo')
            evento_processamento_ok.succeed()


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloBarExpresso()
    modelo.inicia(env)
    env.run(until=60)


if __name__ == '__main__':
    main()
