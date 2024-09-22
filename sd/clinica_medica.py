import itertools
import random
import typing
import numpy.random
import simpy
import simpy.resources.resource


class ModeloClinicaMedica:
    _env: simpy.Environment
    _rnd: numpy.random.Generator
    _resource_medicos: simpy.Resource
    _resource_recepcionistas: simpy.Resource

    # Variáveis para rastreamento de tempos
    _tempo_total_chegada = 0
    _tempo_total_recepcionista_1 = 0
    _tempo_total_ficha = 0
    _tempo_total_consulta = 0
    _tempo_total_recepcionista_2 = 0
    _tempo_total_pagamento = 0
    _num_eventos = 0
    _ultimo_tempo_chegada = 0

    def __init__(self, env: simpy.Environment):
        self._env = env
        self._rnd = numpy.random.default_rng()

        # Recursos
        self._resource_medicos = simpy.Resource(env, capacity=3)
        self._resource_recepcionistas = simpy.Resource(env, capacity=2)

    def inicia(self) -> typing.Generator[simpy.Event, None, None]:
        # Processos de pacientes
        for id_paciente in itertools.count(start=1):
            chegada = self._env.now
            if self._num_eventos > 0:
                tempo_entre_chegadas = chegada - self._ultimo_tempo_chegada
                self._tempo_total_chegada += tempo_entre_chegadas
            self._ultimo_tempo_chegada = chegada

            print(f'{chegada:04.1f}: Paciente {id_paciente:02d} chega na clínica')
            self._env.process(self._processo_atendimento(id_paciente))

            # Chegada média de 3 minutos
            yield self._env.timeout(self._rnd.exponential(3))

    def _processo_atendimento(self, id_paciente: int) -> typing.Generator[simpy.Event, None, None]:
        tempo_inicio = self._env.now

        # Atendimento na recepcionista 1
        tempo_recepcionista_inicio = self._env.now
        with self._resource_recepcionistas.request() as request_recepcionista:
            # Aguarda recepcionista livre
            yield request_recepcionista

            # Preenche a ficha
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} preenche a ficha')
            tempo_ficha_inicio = self._env.now
            yield self._env.timeout(self._rnd.exponential(10))
            tempo_ficha_fim = self._env.now
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} terminou de preencher a ficha')
        tempo_recepcionista_fim = self._env.now
        self._tempo_total_recepcionista_1 += (tempo_recepcionista_fim - tempo_recepcionista_inicio)

        # Tempo de preenchimento da ficha
        self._tempo_total_ficha += (tempo_ficha_fim - tempo_ficha_inicio)

        # Consulta com o médico
        tempo_consulta_inicio = self._env.now
        with self._resource_medicos.request() as request_medico:
            yield request_medico

            # Consulta
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} iniciou sua consulta')
            yield self._env.timeout(self._rnd.exponential(20))
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} terminou sua consulta')
        tempo_consulta_fim = self._env.now
        self._tempo_total_consulta += (tempo_consulta_fim - tempo_consulta_inicio)

        # Atendimento na recepcionista 2
        tempo_recepcionista_2_inicio = self._env.now
        with self._resource_recepcionistas.request() as request_recepcionista:
            # Aguarda recepcionista livre
            yield request_recepcionista

            # Efetua pagamento e agenda a próxima consulta
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} efetua pagamento e agenda próxima consulta')
            tempo_pagamento_inicio = self._env.now
            yield self._env.timeout(random.uniform(1, 4))
            tempo_pagamento_fim = self._env.now
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} saiu da clínica')
        tempo_recepcionista_2_fim = self._env.now
        self._tempo_total_recepcionista_2 += (tempo_recepcionista_2_fim - tempo_recepcionista_2_inicio)

        # Tempo de pagamento e agendamento
        self._tempo_total_pagamento += (tempo_pagamento_fim - tempo_pagamento_inicio)

        # Atualiza o tempo total
        tempo_fim = self._env.now
        self._num_eventos += 1

    def obter_estatisticas(self):
        if self._num_eventos == 0:
            return 0, 0, 0, 0, 0, 0
        media_chegada = self._tempo_total_chegada / self._num_eventos if self._num_eventos > 1 else 0
        media_recepcionista_1 = self._tempo_total_recepcionista_1 / self._num_eventos
        media_ficha = self._tempo_total_ficha / self._num_eventos
        media_consulta = self._tempo_total_consulta / self._num_eventos
        media_recepcionista_2 = self._tempo_total_recepcionista_2 / self._num_eventos
        media_pagamento = self._tempo_total_pagamento / self._num_eventos
        return media_chegada, media_recepcionista_1, media_ficha, media_consulta, media_recepcionista_2, media_pagamento


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloClinicaMedica(env)
    env.process(modelo.inicia())
    env.run(until=3000)
    media_chegada, media_recepcionista_1, media_ficha, media_consulta, media_recepcionista_2, media_pagamento = modelo.obter_estatisticas()
    print(f'Tempo médio entre chegadas dos pacientes: {media_chegada:.2f} minutos')
    print(f'Tempo médio de atendimento pela primeira recepcionista: {media_recepcionista_1:.2f} minutos')
    print(f'Tempo médio de preenchimento de ficha: {media_ficha:.2f} minutos')
    print(f'Tempo médio de consulta com o médico: {media_consulta:.2f} minutos')
    print(f'Tempo médio de atendimento pela segunda recepcionista: {media_recepcionista_2:.2f} minutos')
    print(f'Tempo médio de pagamento e agendamento da próxima consulta: {media_pagamento:.2f} minutos')


if __name__ == '__main__':
    main()
