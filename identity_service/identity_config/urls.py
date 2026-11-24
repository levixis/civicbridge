from django.urls import path
from django.contrib.auth import views as auth
from django.contrib import admin
from common.authentication import EmailOrUsernameAuthenticationForm
from identity import views
urlpatterns=[path('',views.home,name='home'),path('health/',views.health),
 path('authorize/',views.authorize),path('token/',views.token),path('jwks/',views.jwks),path('.well-known/openid-configuration',views.discovery),
 path('accounts/login/',auth.LoginView.as_view(template_name='idp_login.html', authentication_form=EmailOrUsernameAuthenticationForm),name='login'),
 path('accounts/logout/',auth.LogoutView.as_view(),name='logout'),path('accounts/register/',views.register,name='register'),path('admin/',admin.site.urls)]
