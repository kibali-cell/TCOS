from django.urls import include, path
from rest_framework.routers import DefaultRouter

from config.urls import urlpatterns as real_urlpatterns
from tests.rbac_testapp.views import RecordViewSet, StoreRecordViewSet

router = DefaultRouter()
router.register("records", RecordViewSet, basename="record")
router.register("store-records", StoreRecordViewSet, basename="store-record")

urlpatterns = [*real_urlpatterns, path("api/v1/test/", include(router.urls))]
