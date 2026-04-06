import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

import kante
import strawberry
import strawberry_django
from strawberry.types import Info
from django.db.models import Avg, Count, Max, Min, Model, QuerySet, Sum
from django.db.models.functions import (
    TruncDay,
    TruncHour,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)

# ---------- Types ----------


@strawberry.type
class TimeBucket:
    ts: datetime.datetime
    count: int
    distinctCount: int
    max: Optional[float]
    min: Optional[float]
    avg: Optional[float]
    sum: Optional[float]


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
ResolverSpec = Dict[str, Tuple[Callable[[QuerySet, str], Any], Type, str]]


def create_stats_type(
    model: Type[Model],
    *,
    allowed_fields: Dict[str, str],  # GraphQL Enum Name -> Model Field Name
    allowed_datetime_fields: Optional[Dict[str, str]] = None,
    filters: Optional[Type[Any]] = None,
    resolvers: Optional[ResolverSpec] = None,
    type_name: Optional[str] = None,
    enum_name: Optional[str] = None,
    dt_enum_name: Optional[str] = None,
    prescope: Optional[Callable[[QuerySet, Info], QuerySet]] = None,
) -> Tuple[Type[Any], Callable[..., Any]]:
    """
    Build a Strawberry GraphQL Stats type for a Django `model`.

    Returns:
        (StatsType, resolver_function)
    """

    # 1. Create the Field Enum (Numeric fields)
    _enum_name = enum_name or f"{model.__name__}Field"
    # We create a native Python Enum first
    FieldEnumPy = Enum(_enum_name, {k.upper(): k for k in allowed_fields.keys()})
    # Then wrap it with strawberry
    FieldEnum = strawberry.enum(FieldEnumPy, name=_enum_name, description=f"Numeric/aggregatable fields of {model.__name__}")

    # 2. Create the Timestamp Enum (if applicable)
    TimestampEnum = None
    if allowed_datetime_fields:
        _dt_enum_name = dt_enum_name or f"{model.__name__}TimestampField"
        TimestampEnumPy = Enum(_dt_enum_name, {k.upper(): k for k in allowed_datetime_fields.keys()})
        TimestampEnum = strawberry.enum(TimestampEnumPy, name=_dt_enum_name, description=f"Datetime fields of {model.__name__} for bucketing")

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

    def _truncate_expr(dt_field: str, by: Granularity):
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

    @strawberry.type(name=_type_name)
    class StatsType:
        _qs: strawberry.Private[QuerySet]
        # Cache structure: { 'field_name': { 'avg': 10, 'sum': 20... } }
        _cache: strawberry.Private[Dict[str, Dict[str, Any]]]

        def __init__(self, qs: QuerySet):
            self._qs = qs
            self._cache = {}

        def _get_field_stats(self, field_enum: Any) -> Dict[str, Any]:
            model_field = _get_model_field(field_enum)

            if model_field in self._cache:
                return self._cache[model_field]

            # Compute all scalar stats for this field in one query
            # We use standard aliases (avg, sum, etc.)
            stats = self._qs.aggregate(
                distinctCount=Count(model_field, distinct=True),
                max=Max(model_field),
                min=Min(model_field),
                avg=Avg(model_field),
                sum=Sum(model_field),
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
        def max(self, field: FieldEnum) -> Optional[float]:  # type: ignore
            return self._get_field_stats(field)["max"]

        @kante.django_field(description="Minimum value")
        def min(self, field: FieldEnum) -> Optional[float]:  # type: ignore
            return self._get_field_stats(field)["min"]

        @kante.django_field(description="Average value")
        def avg(self, field: FieldEnum) -> Optional[float]:  # type: ignore
            return self._get_field_stats(field)["avg"]

        @kante.django_field(description="Sum of values")
        def sum(self, field: FieldEnum) -> Optional[float]:  # type: ignore
            return self._get_field_stats(field)["sum"]

    # 5. Inject 'series' field only if timestamps are allowed
    if TimestampEnum:

        @kante.django_field(description="Time-bucketed stats over a datetime field.")
        def series(
            self,
            field: FieldEnum,  # type: ignore
            timestamp_field: TimestampEnum,  # type: ignore
            by: Granularity,
        ) -> List[TimeBucket]:
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
                    max=Max(mf),
                    min=Min(mf),
                    avg=Avg(mf),
                    sum=Sum(mf),
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
                        max=row["max"],
                        min=row["min"],
                        avg=row["avg"],
                        sum=row["sum"],
                    )
                )
            return results

        # Dynamically add the series method to the class
        setattr(StatsType, "series", series)

    # 6. Add Custom Resolvers (if any)
    if resolvers:
        for name, (func, ret_type, desc) in resolvers.items():

            def make_custom_resolver(f=func):
                @kante.django_field(description=desc)
                def _wrapper(self, field: FieldEnum) -> ret_type:  # type: ignore
                    mf = _get_model_field(field)
                    return f(self._qs, mf)

                return _wrapper

            setattr(StatsType, name, make_custom_resolver())

    # 7. Create the Root Resolver
    def stats_resolver(root: Any, info: Info, filters: Optional[filters] = None) -> StatsType:
        qs = model.objects.all()

        if prescope:
            qs = prescope(qs, info)

        if filters is not None:
            # Ensure strawberry-django filter backend is working
            qs = strawberry_django.filters.apply(filters, qs, info)

        return StatsType(qs=qs)

    return StatsType, stats_resolver
