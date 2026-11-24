from django.urls import reverse

from integration.contracts import ROLES


def navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {}

    roles = set(user.groups.values_list('name', flat=True))
    education = 'Education Officers' in roles
    operator = user.is_superuser or 'Integration Operators' in roles
    reviewer = bool(roles.intersection(ROLES))
    citizen = hasattr(user, 'citizen') and not (reviewer or operator)
    current = request.resolver_match.url_name if request.resolver_match else None

    links = []
    if citizen:
        links.extend([
            ('Services', 'platform_catalog', 'platform_create'),
            ('My applications', 'platform_workspace', 'platform_detail'),
            ('Department links', 'platform_identities'),
        ])
    elif reviewer or not operator:
        links.append(('Review workspace', 'staff_workspace', 'platform_workspace', 'platform_detail'))
    if operator:
        links.extend([
            ('Platform operations', 'platform_monitor'),
            ('Identity requests', 'platform_claims', 'platform_claim_review'),
            ('Workflows', 'platform_configure', 'platform_new_version'),
        ])
    links.append(('Inbox', 'platform_notifications'))

    return {
        'education_role': education,
        'operator_role': operator,
        'citizen_role': citizen,
        'portal_navigation': [
            {'label': label, 'url': reverse(route), 'current': current in (route, *related)}
            for label, route, *related in links
        ],
    }
