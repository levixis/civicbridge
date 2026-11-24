from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect


class DepartmentWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        routes = getattr(settings, 'SSO_DEPARTMENT_ROUTES', {})
        if request.user.is_authenticated and routes and request.path not in (
            '/accounts/logout/', '/sso/login/', '/sso/callback/',
        ):
            # Existing portal sessions may predate departmental routing.
            identity = request.user.federatedidentity_set.filter(
                issuer=settings.SSO_ISSUER.rstrip('/'), subject__in=routes,
            ).first()
            if identity:
                destination = routes[identity.subject]
                logout(request)
                return redirect(destination)
        return self.get_response(request)
