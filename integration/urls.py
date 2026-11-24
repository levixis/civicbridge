from django.urls import path
from . import views
urlpatterns=[path('',views.catalog,name='platform_catalog'),path('workspace/',views.workspace,name='platform_workspace'),
 path('new/<int:pk>/',views.create,name='platform_create'),path('requests/<uuid:pk>/',views.detail,name='platform_detail'),
 path('requests/<uuid:pk>/consent/',views.grant,name='platform_grant'),path('requests/<uuid:pk>/revoke/',views.revoke,name='platform_revoke'),
 path('requests/<uuid:pk>/review/',views.review,name='platform_review'),path('api/requests/<uuid:pk>/',views.tracker,name='platform_tracker'),
 path('notifications/',views.notifications,name='platform_notifications'),path('notifications/<int:pk>/read/',views.read_notification,name='platform_read_notification'),
 path('configure/',views.configure,name='platform_configure'),path('configure/<int:pk>/',views.configure,name='platform_new_version'),
 path('identities/',views.identities,name='platform_identities'),path('claims/',views.claims,name='platform_claims'),path('claims/<int:pk>/',views.claims,name='platform_claim_review'),
 path('identities/<int:pk>/withdraw/',views.withdraw_claim,name='platform_withdraw_claim'),
 path('monitor/',views.monitor,name='platform_monitor'),path('deliveries/<int:pk>/retry/',views.retry_delivery,name='platform_retry_delivery')]
