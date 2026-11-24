import hashlib
from datetime import timedelta
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from .models import LoginAttempt


class ThrottleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        login_post = request.method == "POST" and request.path in [
            "/accounts/login/",
            "/admin/login/",
        ]
        key = None
        if login_post:
            # Peer address, not untrusted X-Forwarded-For. Behind a proxy this is a conservative shared limit.
            key = hashlib.sha256(
                (
                    request.META.get("REMOTE_ADDR", "unknown")
                    + "|"
                    + request.POST.get("username", "").lower()
                ).encode()
            ).hexdigest()
            with transaction.atomic():
                attempt, _ = LoginAttempt.objects.get_or_create(key=key)
                attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
                if attempt.window_started < timezone.now() - timedelta(minutes=15):
                    attempt.failures = 0
                    attempt.window_started = timezone.now()
                    attempt.save()
                if attempt.failures >= 5:
                    response = HttpResponse(
                        "Too many sign-in attempts. Try again in 15 minutes.",
                        status=429,
                    )
                    response["Retry-After"] = "900"
                    return response
                # Reserve attempts before checking credentials, including concurrent requests.
                attempt.failures += 1
                attempt.save()
        response = self.get_response(request)
        if login_post and response.status_code == 302 and request.user.is_authenticated:
            LoginAttempt.objects.filter(key=key).update(failures=0)
        return response
