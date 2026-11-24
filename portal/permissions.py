STAFF_ROLES = ("Education Officers", "Welfare Officers", "Municipal Reviewers", "Integration Operators")


def is_portal_staff(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__in=STAFF_ROLES).exists()
    )


def is_officer(user):
    return (
        user.is_authenticated and user.groups.filter(name="Education Officers").exists()
    )


def is_revenue(user):
    return (
        user.is_authenticated and user.groups.filter(name="Revenue Officers").exists()
    )


def is_operator(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name="Integration Operators").exists()
    )
