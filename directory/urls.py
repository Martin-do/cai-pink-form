from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/pending/", views.pending, name="pending"),
    path("chancery/signups/", views.signup_list, name="signup_list"),
    path("chancery/signups/<int:pk>/", views.signup_decide, name="signup_decide"),
    path("chancery/priests/", views.priest_list, name="priest_list"),
    path("chancery/priests/new/", views.priest_create, name="priest_create"),
    path("chancery/priests/<int:pk>/", views.priest_detail, name="priest_detail"),
    path("chancery/priests/<int:pk>/unlink/", views.priest_unlink, name="priest_unlink"),
    path("chancery/transfer/", views.transfer, name="transfer"),
    path("chancery/assignments/<int:pk>/end/", views.assignment_end, name="assignment_end"),
    path("chancery/parishes/", views.parish_list, name="parish_list"),
    path("chancery/parishes/new/", views.parish_create, name="parish_create"),
    path("chancery/parishes/<int:pk>/", views.parish_detail, name="parish_detail"),
]
