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


@dataclasses.dataclass
class Preparo:
    copo: Copo | None


@dataclasses.dataclass
class Retirada:
    copo: Copo
    id_cliente: int


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
    _store_funcionarios: simpy.Store = sd.RecursoModelo(descricao='Funcionários')
    _store_copos: simpy.Store = sd.RecursoModelo(descricao='Copos')
    _resource_cadeiras: simpy.Resource = sd.RecursoModelo(descricao='Cadeiras')
    _resource_lavagem: simpy.Resource = sd.RecursoModelo(descricao='Copos (pia)')

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

        env.process(self._processa_clientes(env))

    def _processa_clientes(self, env: simpy.Environment) -> sd.Generator:
        for id_cliente in itertools.count(start=1):
            env.process(self._processa_cliente(env, id_cliente))

            # Os clientes chegam em média a cada 4 min
            # de acordo com uma função exponencial
            yield env.timeout(self._rnd.exponential(4))

    @sd.entrypoint
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

                # Aguarda até que o evento seja concluído pelo funcionário
                yield env.process(self._processa_funcionario__coleta(env, Coleta(
                    id_pedido=idx_pedido + 1,
                    id_cliente=id_cliente,
                )))
                self._tempos_espera_pedir_cliente.append(env.now - tempo_inicio_espera_pedir)

                tempo_inicio_espera_consumir = env.now
                # (Fila) Aguarda pedido ficar pronto
                log(f'pedido {idx_pedido + 1}/{qtd_pedidos}', 'aguarda pedido ser preparado')

                # Aguarda até que o evento seja concluído pelo funcionário
                copo_pedido: Copo = yield env.process(self._processa_funcionario__preparo(env, copo_cliente))
                tempo_espera_consumir = env.now - tempo_inicio_espera_consumir
                self._tempos_espera_consumir_cliente.append(tempo_espera_consumir)
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
            env.process(self._processa_funcionario__retirada(env, Retirada(
                copo=copo_cliente,
                id_cliente=id_cliente,
            )))

        self._tempos_estadia_cliente.append(env.now - tempo_inicio_estadia)

    def _processa_funcionario__coleta(self, env: simpy.Environment, coleta: Coleta) -> sd.Generator:
        # (Fila) Aguarda funcionário
        funcionario: Funcionario = yield self._store_funcionarios.get()
        log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

        # [Atividade] Coleta do pedido
        # Funcionários atendem o pedido em 0,7min com desvio de 0,3min
        log(f'coleta pedido {coleta.id_pedido} do cliente {coleta.id_cliente}')
        yield env.timeout(abs(self._rnd.normal(0.7, scale=0.3)))

        self._store_funcionarios.put(funcionario)

    def _processa_funcionario__preparo(self, env: simpy.Environment, copo_cliente: Copo | None) -> sd.Generator:
        # (Fila) Aguarda funcionário
        funcionario: Funcionario = yield self._store_funcionarios.get()
        # [Atividade] Ocupa funcionário
        log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

        tempo_inicial_preparo = env.now

        copo: Copo
        # Se o cliente ainda não possuir um copo
        if copo_cliente is None:
            # (Fila) Aguarda copo
            novo_copo = yield self._store_copos.get()

            # [Atividade] Ocupa copo
            log('ocupa copo')
            copo = novo_copo

        # Copo reutilizado do último pedido do cliente
        else:
            copo = copo_cliente

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
        yield env.timeout(abs(self._rnd.normal(0.5, scale=0.1)))
        log('coloca copo no freezer')

        # Desocupa funcionário
        yield self._store_funcionarios.put(funcionario)

        # (Fila) Aguarda copo congelar
        # O copo deve ficar no freezer por 4min antes de ser usado para servir
        log('aguarda copo congelar')
        yield env.timeout(4)

        self._tempos_preparo.append(env.now - tempo_inicial_preparo)

        log('retira copo do freezer')
        copo.limpo = False
        return copo

    def _processa_funcionario__retirada(self, env: simpy.Environment, retirada: Retirada) -> sd.Generator:
        # (Fila) Aguarda funcionário
        funcionario: Funcionario = yield self._store_funcionarios.get()
        log = functools.partial(self._log, env, f'funcionário {funcionario.id}')

        # [Atividade] Recolhe o copo da mesa
        log(f'recolhe o copo da mesa do cliente {retirada.id_cliente}')
        yield env.timeout(abs(self._rnd.normal(0.7, scale=0.3)))

        self._store_copos.put(retirada.copo)

        self._store_funcionarios.put(funcionario)


def main() -> None:
    sd.executa_script(ModeloBarExpresso, y_range=(0, 30, 5))


if __name__ == '__main__':
    main()
