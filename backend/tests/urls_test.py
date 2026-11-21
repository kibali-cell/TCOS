from django.urls import include, path
from rest_framework.routers import DefaultRouter

from config.urls import urlpatterns as real_urlpatterns
from tests.rbac_testapp.views import RecordViewSet

router = DefaultRouter()
router.register("records", RecordViewSet, basename="record")

urlpatterns = [*real_urlpatterns, path("api/v1/test/", include(router.urls))]
