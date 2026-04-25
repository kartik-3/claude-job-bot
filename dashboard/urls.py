from django.urls import path
from . import views

urlpatterns = [
    path("api/jobs/", views.jobs_list),
    path("api/jobs/<str:job_id>/", views.job_update),
]
