import datetime
from collections.abc import Callable
from enum import Enum

import kante
import strawberry
import strawberry_django
from django.db.models import (
    Aggregate,
    Avg,
    Count,
    DecimalField,
    FloatField,
    IntegerField,
    Max,
    Min,
    Model,
    QuerySet,
    Sum,
)
from django.db.models.functions import (
    TruncDay,
    TruncHour,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from django.db.models.functions.datetime import TruncBase
from strawberry.types import Info
from strawberry_django.fields.field import StrawberryDjangoField

from evidence.values import JSONValue

# ---------- Types ----------


@strawberry.type
class TimeBucket:
    ts: datetime.datetime
    count: int
    distinctCount: int
    max: float | None
    min: float | None
    avg: float | None
    sum: float | None


@strawberry.enum
class Granularity(str, Enum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


# ---------- Resolver Spec ----------
# (Resolver Function, Return Type, Description)
ResolverSpec = dict[str, tuple[Callable[[QuerySet[Model], str], object], type, str]]


def create_stats_type(
    model: type[Model],
    *,
    scope: Callable[[Info], "QuerySet[Model]"],
    allowed_fields: dict[str, str],  # GraphQL Enum Name -> Model Field Name
    allowed_datetime_fields: dict[str, str] | None = None,
    filters: type | None = None,
    resolvers: ResolverSpec | None = None,
    type_name: str | None = None,
    enum_name: str | None = None,
    dt_enum_name: str | None = None,
) -> tuple[type, Callable[..., object]]:
    """
    Build a Strawberry GraphQL Stats type for a Django `model`.

    `scope` produces the base queryset from the request — there is no spelling
    of "just aggregate all rows", because every model counted here is tenant
    data. The predecessor (`model.objects.all()` plus an optional `prescope`
    nobody passed) aggregated across organizations for the core models and
    raised `UnscopedEvidenceAccess` outright for the evidence ones.

    Returns:
        (StatsType, resolver_function)
    """

    # 0. Refuse a field the model does not have, here rather than per request:
    # a stats type over a column that does not exist builds and serves `count`
    # fine and raises a FieldError on every other field.
    for column in [*allowed_fields.values(), *(allowed_datetime_fields or {}).values()]:
        model._meta.get_field(column)

    # max/min/avg/sum are Floats: they are taken of numeric columns only. Over a
    # timestamp `AVG` does not exist in Postgres and `MAX` is not a float, so a
    # non-numeric field answers them with null and still counts its distinct values.
    numeric = {
        column
        for column in allowed_fields.values()
        if isinstance(
            model._meta.get_field(column), (IntegerField, FloatField, DecimalField)
        )
    }

    def _aggregates(column: str) -> dict[str, Aggregate]:
        if column in numeric:
            return {
                "max": Max(column),
                "min": Min(column),
                "avg": Avg(column),
                "sum": Sum(column),
            }
        return {}

    # 1. Create the Field Enum (Numeric fields)
    _enum_name = enum_name or f"{model.__name__}Field"
    # We create a native Python Enum first
    FieldEnumPy = Enum(_enum_name, {k.upper(): k for k in allowed_fields.keys()})
    # Then wrap it with strawberry
    FieldEnum = strawberry.enum(
        FieldEnumPy,
        name=_enum_name,
        description=f"Numeric/aggregatable fields of {model.__name__}",
    )

    # 2. Create the Timestamp Enum (if applicable)
    TimestampEnum = None
    if allowed_datetime_fields:
        _dt_enum_name = dt_enum_name or f"{model.__name__}TimestampField"
        TimestampEnumPy = Enum(
            _dt_enum_name, {k.upper(): k for k in allowed_datetime_fields.keys()}
        )
        TimestampEnum = strawberry.enum(
            TimestampEnumPy,
            name=_dt_enum_name,
            description=f"Datetime fields of {model.__name__} for bucketing",
        )

    # 3. Helpers
    def _get_model_field(enum_value: Enum) -> str:
        """Resolve the GraphQL enum value to the actual Django DB field name."""
        if isinstance(enum_value, FieldEnumPy):
            return allowed_fields[enum_value.name.lower()]
        # Handle case where enum_value might be the raw value depending on Strawberry version
        return allowed_fields[enum_value.name.lower()]

    def _get_timestamp_field(enum_value: Enum) -> str:
        if allowed_datetime_fields is None:
            raise ValueError("No datetime fields configured")
        return allowed_datetime_fields[enum_value.name.lower()]

    def _truncate_expr(dt_field: str, by: Granularity) -> TruncBase:
        if by == Granularity.HOUR:
            return TruncHour(dt_field)
        elif by == Granularity.DAY:
            return TruncDay(dt_field)
        elif by == Granularity.WEEK:
            return TruncWeek(dt_field)
        elif by == Granularity.MONTH:
            return TruncMonth(dt_field)
        elif by == Granularity.QUARTER:
            return TruncQuarter(dt_field)
        elif by == Granularity.YEAR:
            return TruncYear(dt_field)
        return TruncDay(dt_field)

    # 4. Define the Stats Class dynamically
    # We define it locally so it captures the Enums created above in its closure.

    _type_name = type_name or f"{model.__name__}Stats"

    class StatsType:
        _qs: strawberry.Private[QuerySet]
        # Cache structure: { 'field_name': { 'avg': 10, 'sum': 20... } }
        _cache: strawberry.Private[dict[str, dict[str, JSONValue]]]

        def __init__(self, qs: QuerySet) -> None:
            self._qs = qs
            self._cache = {}

        def _get_field_stats(self, field_enum: object) -> dict[str, JSONValue]:
            model_field = _get_model_field(field_enum)

            if model_field in self._cache:
                return self._cache[model_field]

            # Compute all scalar stats for this field in one query
            # We use standard aliases (avg, sum, etc.)
            stats = self._qs.aggregate(
                distinctCount=Count(model_field, distinct=True),
                **_aggregates(model_field),
            )
            self._cache[model_field] = stats
            return stats

        # --- Fields ---

        @kante.django_field(description="Total number of items in the selection")
        def count(self) -> int:
            return self._qs.count()

        @kante.django_field(description="Count of distinct values")
        def distinctCount(self, field: FieldEnum) -> int:  # type: ignore
            return self._get_field_stats(field)["distinctCount"]

        @kante.django_field(description="Maximum value")
        def max(self, field: FieldEnum) -> float | None:  # type: ignore
            return self._get_field_stats(field).get("max")

        @kante.django_field(description="Minimum value")
        def min(self, field: FieldEnum) -> float | None:  # type: ignore
            return self._get_field_stats(field).get("min")

        @kante.django_field(description="Average value")
        def avg(self, field: FieldEnum) -> float | None:  # type: ignore
            return self._get_field_stats(field).get("avg")

        @kante.django_field(description="Sum of values")
        def sum(self, field: FieldEnum) -> float | None:  # type: ignore
            return self._get_field_stats(field).get("sum")

    # 5. Inject 'series' field only if timestamps are allowed
    if TimestampEnum:

        @kante.django_field(description="Time-bucketed stats over a datetime field.")
        def series(
            self: StatsType,
            field: FieldEnum,  # type: ignore
            timestamp_field: TimestampEnum,  # type: ignore
            by: Granularity,
        ) -> list[TimeBucket]:
            mf = _get_model_field(field)
            tf = _get_timestamp_field(timestamp_field)
            trunc_expr = _truncate_expr(tf, by)

            # 1 Query: Group by Truncated Date -> Aggregate Stats
            qs_data = (
                self._qs.annotate(bucket=trunc_expr)
                .values("bucket")
                .annotate(
                    count=Count("pk"),
                    distinctCount=Count(mf, distinct=True),
                    **_aggregates(mf),
                )
                .order_by("bucket")
            )

            results = []
            for row in qs_data:
                # Handle potential None for bucket (if field is nullable)
                if row["bucket"] is None:
                    continue

                results.append(
                    TimeBucket(
                        ts=row["bucket"],
                        count=row["count"],
                        distinctCount=row["distinctCount"],
                        max=row.get("max"),
                        min=row.get("min"),
                        avg=row.get("avg"),
                        sum=row.get("sum"),
                    )
                )
            return results

        # Dynamically add the series method to the class
        StatsType.series = series

    # 6. Add Custom Resolvers (if any)
    if resolvers:
        for name, (func, ret_type, desc) in resolvers.items():

            def make_custom_resolver(
                f: Callable[[QuerySet[Model], str], object] = func,
                desc: str = desc,
                ret_type: type = ret_type,
            ) -> StrawberryDjangoField:
                @kante.django_field(description=desc)
                def _wrapper(self: StatsType, field: FieldEnum) -> ret_type:  # type: ignore
                    mf = _get_model_field(field)
                    return f(self._qs, mf)

                return _wrapper

            setattr(StatsType, name, make_custom_resolver())

    # Decorated last: strawberry reads the class's fields when it is decorated,
    # so `series` and the custom resolvers have to be on it by then. They used to
    # be attached afterwards, and no stats type ever offered them.
    StatsType = strawberry.type(name=_type_name)(StatsType)

    # 7. Create the Root Resolver
    def stats_resolver(
        root: object, info: Info, filters: filters | None = None
    ) -> StatsType:
        qs = scope(info)

        if filters is not None:
            # Ensure strawberry-django filter backend is working
            qs = strawberry_django.filters.apply(filters, qs, info)

        return StatsType(qs=qs)

    return StatsType, stats_resolver
