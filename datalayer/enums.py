from django.db.models import TextChoices


class DatalayerStoreKindChoices(TextChoices):
    """Which kind of object a `DatalayerStore` row points at.

    Stores used to be a multi-table inheritance chain. They are now one table, and the
    former subclasses are proxies that differ only in behaviour -- how a read grant is
    minted, what `fill_info` records after an upload -- so this column is what tells
    them apart.
    """

    BIG_FILE = "BIG_FILE"
    MEDIA = "MEDIA"
    ZARR = "ZARR"
    PARQUET = "PARQUET"
