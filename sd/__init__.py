import builtins
import dataclasses
import os
import statistics
import tomllib
import typing

import arrow
import matplotlib.pyplot as plt
import numpy.random
import simpy

Generator = typing.Generator[simpy.Event, typing.Any, typing.Any]


def executa_script(
        M,
        x_range: tuple[int, int, int] = (30, 360, 30),
        y_range: tuple[int, int, int] = (0, 120, 15),
) -> None:
    try:
        with open(os.path.join(os.path.dirname(os.getcwd()), 'config.toml'), 'rb') as f:
            dados = tomllib.load(f)
    except FileNotFoundError:
        dados = {}

    dados_geral = dados.get('geral', {})
    seed = dados_geral.get('seed')
    tempo_maximo = dados_geral.get('tempo-maximo', 60)

    dados_grafico = dados.get('grafico', {})
    deve_exibir_grafico = dados_grafico.get('exibir', False)

    dados_modelos = dados.get('modelos', {})

    if not deve_exibir_grafico:
        env = simpy.Environment()
        modelo = M.from_json(seed, True, dados_modelos)
        modelo.executa(env)
        env.run(until=tempo_maximo)
        modelo.exibe_estado()
        return

    _plot(
        lambda: M.from_json(seed, False, dados_modelos),
        metricas=M.lista_metricas(),
        descritor_metrica=M.descreve_metrica,
        x_range=x_range,
        y_range=y_range,
        time_unit=M.time_unit(),
    )


@dataclasses.dataclass(kw_only=True, frozen=True)
class ParametroModelo:
    chave: str


@dataclasses.dataclass(kw_only=True, frozen=True)
class MetricaModelo:
    descricao: str


class ModeloMetaclass(type):
    def _log_stats(
            cls,
            prefix: str,
            values: list[float],
    ) -> None:
        expected_time_unit_values = ('horas', 'minutos')
        time_unit = getattr(cls, 'unidade_tempo', 'minutos')
        if time_unit not in expected_time_unit_values:
            raise ValueError(
                f'invalid value for time_unit: '
                f'expected ({', '.join(expected_time_unit_values)}), got {time_unit}'
            )

        def fmt(delta: float) -> str:
            dt = arrow.utcnow()
            match time_unit:
                case 'horas':
                    dt = dt.shift(hours=delta)
                case 'minutos':
                    dt = dt.shift(minutes=delta)
            return dt.humanize(locale='pt', only_distance=True, granularity=['hour', 'minute', 'second'])

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)
        print(f'{prefix}: {fmt(mean)} (± {stdev:.2f}), min={fmt(min(values))}, max={fmt(max(values))}')

    def _get_metrics(cls) -> dict[str, MetricaModelo]:
        try:
            return cls.__base_metrics
        except AttributeError:
            return {
                field_name: field_value
                for field_name, _ in cls.__annotations__.items()
                if isinstance(field_value := getattr(cls, field_name, None), MetricaModelo)
            }

    def _get_parameters(cls) -> dict[str, ParametroModelo]:
        return {
            field_name: field_value
            for field_name in dir(cls)
            if isinstance(field_value := getattr(cls, field_name), ParametroModelo)
        }

    def _initialize_parameters_fields(cls, kwargs: dict[str, typing.Any]) -> None:
        expected_arguments = {field_name for field_name, _ in cls._get_parameters().items()}
        actual_arguments = set(kwargs.keys()) & expected_arguments
        missing_arguments = expected_arguments - actual_arguments
        if missing_arguments:
            raise ValueError(f'missing arguments for {cls.__name__}: {', '.join(missing_arguments)}')
        for field_name in expected_arguments:
            setattr(cls, field_name, kwargs.pop(field_name))

    def _initialize_metrics_fields(cls) -> None:
        base_metrics: dict[str, MetricaModelo] = {}
        for field_name, annotation in cls._get_metrics().items():
            field_type = cls.__annotations__[field_name]
            while field_parent_type := typing.get_origin(field_type):
                field_type = field_parent_type

            default_value: object
            match field_type:
                case builtins.int:
                    default_value = 0
                case builtins.float:
                    default_value = 0.0
                case builtins.bool:
                    default_value = False
                case builtins.list:
                    default_value = []
                case builtins.dict:
                    default_value = {}
                case builtins.tuple:
                    default_value = ()
                case builtins.set:
                    default_value = set()
                case builtins.str:
                    default_value = ''
                case _:
                    raise ValueError(f'unsupported type: {field_type}')

            setattr(cls, field_name, default_value)
            base_metrics[field_name] = annotation
        cls.__base_metrics = base_metrics

    def from_json(cls, seed: int | None, deve_exibir_log: bool, data: dict[str, typing.Any]):
        model_key = getattr(cls, 'chave_modelo', None)
        if not model_key:
            raise ValueError('model must have a annotation named \'chave_modelo\'')
        model_data = data.get(model_key, {})

        expected_map: dict[str, str] = {
            parameter.chave: field_name
            for field_name, parameter in cls._get_parameters().items()
        }
        actual_keys = set(model_data.keys()) & set(expected_map.keys())
        missing_keys = set(expected_map.keys()) - actual_keys
        if missing_keys:
            raise ValueError(f'missing keys for {cls.__name__}: {', '.join(missing_keys)}')
        parameters_kwargs = {
            field_name: model_data[field_key]
            for field_key, field_name in expected_map.items()
        }
        return cls(
            seed=seed,
            deve_exibir_log=deve_exibir_log,
            **parameters_kwargs,
        )

    def time_unit(cls) -> str:
        match unidade_tempo := getattr(cls, 'unidade_tempo'):
            case 'horas':
                return 'hours'
            case 'minutos':
                return 'minutes'
            case _:
                raise ValueError(f'invalid value for time unit: {unidade_tempo}')

    def descreve_metrica(cls, metrica: MetricaModelo) -> str:
        return metrica.descricao

    def lista_metricas(cls) -> list[MetricaModelo]:
        return [
            annotation
            for field_name, annotation in cls._get_metrics().items()
            if cls.__annotations__[field_name] == list[float]
        ]

    def __call__(
            cls,
            *,
            deve_exibir_log: bool = True,
            seed: int = None,
            **kwargs,
    ):
        cls._deve_exibir_log = deve_exibir_log
        cls._rnd = numpy.random.default_rng(seed)
        cls._initialize_parameters_fields(kwargs)

        def _log(self, env: simpy.Environment, *args: str) -> None:
            if self._deve_exibir_log:
                print(f'{env.now:05.2f}', *args, sep=': ')

        cls._log = _log

        def exibe_estado(self):
            for field_name, annotation in cls._get_metrics().items():
                field_type = cls.__annotations__[field_name]
                if field_type == list[float]:
                    prefix = annotation.descricao
                    cls._log_stats(prefix, getattr(self, field_name))

        cls.exibe_estado = exibe_estado

        def calcula_metrica(self, metrica: MetricaModelo) -> str:
            field_name = next(
                field_name
                for field_name, annotation in cls.__base_metrics.items()
                if annotation is metrica
            )
            return getattr(self, field_name)

        cls.calcula_metrica = calcula_metrica

        executa_1 = getattr(cls, 'executa', None)
        if executa_1 is None:
            raise ValueError(
                'model must have a method named \'executa\': `def executa(self, env: simpy.Environment) -> None`'
            )

        def executa_2(self, env: simpy.Environment) -> None:
            cls._initialize_metrics_fields()
            return executa_1(self, env)

        cls.executa = executa_2

        return super().__call__(**kwargs)


def _plot[M](
        criador_modelo: typing.Callable[[], M],
        metricas: typing.Sequence[MetricaModelo],
        descritor_metrica: typing.Callable[[MetricaModelo], str],
        x_range: tuple[int, int, int],
        y_range: tuple[int, int, int],
        time_unit: typing.Literal['hours', 'minutes'] = 'minutes',
) -> None:
    min_x, max_x, step_x = x_range
    min_y, max_y, step_y = y_range

    x = []
    medidas: dict[M, list[float]] = {}
    for until in range(min_x, max_x + 1, step_x):
        env = simpy.Environment()
        modelo = criador_modelo()
        modelo.executa(env)
        env.run(until=until)

        x.append(until)
        for metrica in metricas:
            valores = modelo.calcula_metrica(metrica)
            medidas.setdefault(metrica, []).append(statistics.mean(valores))

    fig, ax = plt.subplots()
    for metrica in metricas:
        y = medidas[metrica]
        ax.plot(x, y, label=descritor_metrica(metrica))

    ax.set_xlabel('Tempo da simulação')
    ax.set_ylabel('Tempo médio da ação')

    def major_formatter(value: float, _: float) -> str:
        days: float
        hours: float
        minutes: float
        match time_unit:
            case 'hours':
                days, hours = divmod(value, 24)
                minutes = 0
            case 'minutes':
                days, hm = divmod(value, 1440)
                hours, minutes = divmod(hm, 60)
            case _:
                typing.assert_never(time_unit)

        tokens: list[str] = []
        if days > 0:
            tokens.append(f'{days}d')
        if hours > 0:
            tokens.append(f'{hours}h')
        if minutes > 0:
            tokens.append(f'{minutes}m')
        return ''.join(tokens)

    ax.xaxis.set_major_formatter(major_formatter)
    ax.yaxis.set_major_formatter(major_formatter)
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_xticks(list(range(min_x, max_x + 1, step_x)))
    ax.set_yticks(list(range(min_y, max_y + 1, step_y)))
    ax.grid(axis='y')
    ax.legend()
    plt.show()
