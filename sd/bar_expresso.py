import dataclasses
import functools
import itertools

import simpy.resources.resource

import sd


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
class Retirada:
    copo: Copo
    id_cliente: int
    evento_conclusao: simpy.Event | None


@dataclasses.dataclass
class Funcionario:
    id: int


class ModeloBarExpresso(metaclass=sd.ModeloMetaclass):
    # Configuração do modelo
    chave_modelo: str = 'bar-expresso'
    unidade_tempo: str = 'minutos'

    _qtd_funcionarios: int = sd.ParametroModelo(chave='qtd-funcionarios')
    _qtd_cadeiras: int = sd.ParametroModelo(chave='qtd-cadeiras')
    _qtd_copos: int = sd.ParametroModelo(chave='qtd-copos')
    _qtd_copos_pia: int = sd.ParametroModelo(chave='qtd-copos-pia')

    _no_pedidos_consumidos: int = sd.MetricaModelo(descricao='Número de pedidos consumidos')
    _tempos_estadia_cliente: list[float] = sd.MetricaModelo(descricao='Tempo estadia')
    _tempos_espera_sentar_cliente: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ sentar')
    _tempos_espera_pedir_cliente: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ pedir')
    _tempos_espera_consumir_cliente: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ consumir')
    _tempos_preparo: list[float] = sd.MetricaModelo(descricao='Tempo preparo')

    # Implementação do modelo
    _store_funcionarios: simpy.Store
    _store_copos: simpy.Store
    _resource_cadeiras: simpy.Resource
    _resource_lavagem: simpy.Resource

    _eventos_preparo: simpy.Store
    _eventos_coleta: simpy.Store
    _eventos_retirada: simpy.Store

    def executa(self, env: simpy.Environment) -> None:
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
        self._eventos_retirada = simpy.Store(env)
        env.process(self._processa_clientes(env))
        env.process(self._processa_funcionario__preparo(env))
        env.process(self._processa_funcionario__coleta(env))
        env.process(self._processa_funcionario__retirada(env))

    def _processa_clientes(self, env: simpy.Environment) -> sd.Generator:
        for id_cliente in itertools.count(start=1):
            env.process(self._processa_cliente(env, id_cliente))

            # Os clientes chegam em média a cada 4 min
            # de acordo com uma função exponencial
            yield env.timeout(self._rnd.exponential(4))

    def _processa_cliente(self, env: simpy.Environment, id_cliente: int) -> sd.Generator:
        log = functools.partial(self._log, env, f'cliente {id_cliente}')
        log('chega')
        tempo_inicio_estadia = env.now

        copo_cliente: Copo | None = None

        with self._resource_cadeiras.request() as request_cadeira:
            tempo_inicio_espera_sentar = env.now

            # (Fila) Aguarda cadeira
            yield request_cadeira

            # [Atividade] Ocupa cadeira
            self._tempos_espera_sentar_cliente.append(env.now - tempo_inicio_espera_sentar)

            # A probabilidade de um cliente tomar 1 copo é de 0,3; 2 copos 0,45; 3 copos 0,2; e 4 copos 0,05.
            qtd_pedidos = self._rnd.choice([1, 2, 3, 4], p=[0.3, 0.45, 0.2, 0.05])
            log(f'ocupa cadeira e pretende consumir {qtd_pedidos} pedidos')

            for idx_pedido in range(qtd_pedidos):
                # (Fila) Aguarda funcionário ficar disponível para coletar o pedido
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'aguarda funcionário ficar disponível')
                tempo_inicio_espera_pedir = env.now

                evento_coleta = env.event()
                self._eventos_coleta.put(evento_coleta)  # Coloca um evento na fila de coleta do funcionário

                evento_conclusao_coleta = env.event()
                evento_coleta.succeed(
                    value=Coleta(
                        id_pedido=idx_pedido + 1,
                        id_cliente=id_cliente,
                        evento_conclusao=evento_conclusao_coleta,
                    )
                )
                yield evento_conclusao_coleta  # Aguarda até que o evento seja concluído pelo funcionário
                self._tempos_espera_pedir_cliente.append(env.now - tempo_inicio_espera_pedir)

                tempo_inicio_espera_consumir = env.now
                # (Fila) Aguarda pedido ficar pronto
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'aguarda pedido ser preparado')

                evento_preparo = env.event()
                self._eventos_preparo.put(evento_preparo)  # Coloca um evento na fila de preparo do funcionário

                evento_conclusao_preparo = env.event()
                evento_preparo.succeed(
                    value=Preparo(copo=copo_cliente, evento_conclusao=evento_conclusao_preparo),
                )
                # Aguarda até que o evento seja concluído pelo funcionário
                copo_pedido: Copo = yield evento_conclusao_preparo
                self._tempos_espera_consumir_cliente.append(env.now - tempo_inicio_espera_consumir)
                if copo_cliente is None:
                    copo_cliente = copo_pedido

                # [Atividade] Consume pedido
                # Os clientes levam em média 3 min para consumir uma bebida de acordo
                # com uma função normal com desvio padrão de 1min
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'consome pedido')
                yield env.timeout(abs(self._rnd.normal(3, scale=1)))

                self._no_pedidos_consumidos += 1

        log('vai embora')
        if copo_cliente is not None:
            evento_retirada = env.event()
            self._eventos_retirada.put(evento_retirada)  # Coloca um evento na fila de retirada do funcionário
            evento_retirada.succeed(
                value=Retirada(
                    copo=copo_cliente,
                    id_cliente=id_cliente,
                    evento_conclusao=None,
                )
            )

        self._tempos_estadia_cliente.append(env.now - tempo_inicio_estadia)

    def _processa_funcionario__coleta(self, env: simpy.Environment) -> sd.Generator:
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

            self._store_funcionarios.put(funcionario)

            coleta.evento_conclusao.succeed()

    def _processa_funcionario__preparo(self, env: simpy.Environment) -> sd.Generator:
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
            self._store_funcionarios.put(funcionario)

            # (Fila) Aguarda copo congelar
            # O copo deve ficar no freezer por 4min antes de ser usado para servir
            log('aguarda copo congelar')
            yield env.timeout(4)

            self._tempos_preparo.append(env.now - tempo_inicial_preparo)

            log('retira copo do freezer')
            preparo.evento_conclusao.succeed(value=copo)

    def _processa_funcionario__retirada(self, env: simpy.Environment) -> sd.Generator:
        while True:
            # Aguarda um evento ser colocado na fila de retirada
            evento_retirada = yield self._eventos_retirada.get()
            retirada: Retirada = yield evento_retirada

            # (Fila) Aguarda funcionário
            funcionario: Funcionario = yield self._store_funcionarios.get()
            log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

            # [Atividade] Recolhe o copo da mesa
            log(f'recolhe o copo da mesa do cliente {retirada.id_cliente}')
            yield env.timeout(abs(self._rnd.normal(0.7, scale=0.3)))

            self._store_copos.put(retirada.copo)

            self._store_funcionarios.put(funcionario)
            if evento_conclusao := retirada.evento_conclusao:
                evento_conclusao.succeed()


def main() -> None:
    sd.executa_script(ModeloBarExpresso)


if __name__ == '__main__':
    main()
