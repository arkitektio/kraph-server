"""The identity the static test token authenticates as.

Fixtures must build graphs under *this* organization, not one of their own
invention: the auth extension overwrites the request's user and organization at
execution time, so a graph owned by anything else belongs to a tenant the request
cannot act for.
"""

from authentikate.models import Membership, Organization, User

STATIC_USERNAME = "static_issuer_1"
STATIC_ORG_SLUG = "static_org"


def static_identity() -> tuple[User, Organization, Membership]:
    """The user, organization and membership the static test token authenticates as."""
    user, _ = User.objects.get_or_create(username=STATIC_USERNAME, defaults={"sub": "1", "iss": "static_issuer"})
    org, _ = Organization.objects.get_or_create(slug=STATIC_ORG_SLUG)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org)
    return user, org, membership
