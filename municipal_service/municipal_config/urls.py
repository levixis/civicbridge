from django.urls import path
from django.contrib import admin
from django.contrib.auth import views as auth
from municipal import views
from source_bridge import views as events
from federation import views as sso
urlpatterns=[
 path('',views.registry,name='registry'),path('records/new/',views.edit,name='issue'),path('records/<int:pk>/',views.edit,name='edit'),
 path('health/',views.health),path('api/v1/residence/<str:subject>/',views.record_api),
 path('api/v1/legacy/household/<str:subject>/',views.record_api,{'legacy':True}),
 path('api/v1/events/',events.receive),path('tracker/',events.tracker,name='source_tracker'),
 path('sso/login/',sso.start,name='sso_start'),path('sso/callback/',sso.callback,name='sso_callback'),
 path('accounts/login/',auth.LoginView.as_view(template_name='source_login.html'),name='login'),
 path('accounts/logout/',sso.SharedSignOutView.as_view(),name='logout'),path('admin/',admin.site.urls)]
