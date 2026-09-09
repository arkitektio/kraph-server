"""One category per declared word per view (RFC 0021).

`(graph, key)` implied it, because a category's term is minted from its key —
but the term→category map the projector kept assumed it silently, and the
database is where an invariant belongs. Several categories for one word in one
view arise only by derivation (a defined category's clauses naming the word),
and those are resolved by admission, never by a map.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_images_do_not_cascade"),
        ("datalayer", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(condition=models.Q(("term__isnull", False)), fields=("graph", "term"), name="one_category_per_word_per_view"),
        ),
    ]
