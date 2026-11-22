"""The identity the static test token authenticates as.

Fixtures must build graphs under *this* organization, not one of their own
invention: the auth extension overwrites the request's user and organization at
execution time, so a graph owned by anything else belongs to a tenant the request
cannot act for.
"""

from typing import TypedDict

from authentikate.models import Membership, Organization, User
from kante.context import UniversalRequest

STATIC_USERNAME = "static_issuer_1"
STATIC_ORG_IDENTIFIER = "static_issuer#static_org"


def static_identity() -> tuple[User, Organization, Membership]:
    """The user, organization and membership the static test token authenticates as."""
    user, _ = User.objects.get_or_create(
        username=STATIC_USERNAME, defaults={"sub": "1", "iss": "static_issuer"}
    )
    org, _ = Organization.objects.get_or_create(identifier=STATIC_ORG_IDENTIFIER)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org)
    return user, org, membership


class Owner(TypedDict):
    """Who a view is materialized for: `materialize(..., **owned_by(request))`."""

    user: User
    organization: Organization
    membership: Membership


def owned_by(request: UniversalRequest) -> Owner:
    """The request's user, organization and membership, as the rows they are.

    `UniversalRequest` types its principals as kante's protocols; every context
    this suite builds carries the authentikate rows themselves, which is what
    `materialize` and the ORM take.
    """
    user, organization, membership = (
        request._user,
        request._organization,
        request.membership,
    )
    assert isinstance(user, User)
    assert isinstance(organization, Organization)
    assert isinstance(membership, Membership)
    return Owner(user=user, organization=organization, membership=membership)
