from django.urls import path
from .views import (
    MedicalRecordListCreateView,
    MedicalRecordDetailView,
    MedicalRecordByPetView,
    MedicalRecordServiceListCreateView,
    MedicalRecordServiceDeleteView,
    MedicalRecordSummaryView,
    VitalSignsListCreateView,
    close_medical_record,
    medical_record_pdf,
    protocol_analytics,
    VaccineRecordListCreateView,
    VaccineRecordDetailView,
)

urlpatterns = [
    path("medical-records/", MedicalRecordListCreateView.as_view()),
    # DEBE ir antes del catch-all <str:pk> (si no, "protocol-analytics" se toma como pk).
    path("medical-records/protocol-analytics/", protocol_analytics),
    path("medical-records/<str:pk>/", MedicalRecordDetailView.as_view()),
    path("medical-records/<str:pk>/close/", close_medical_record),
    path("medical-records/<str:pk>/vitals/", VitalSignsListCreateView.as_view()),
    path("medical-records/<str:pk>/summary/", MedicalRecordSummaryView.as_view()),
    path("medical-records/<str:pk>/pdf/", medical_record_pdf),
    path("medical-records/pet/<str:pet_public_id>/", MedicalRecordByPetView.as_view()),
    path("medical-records/<str:medical_record_pk>/services/", MedicalRecordServiceListCreateView.as_view()),
    path("medical-records/<str:medical_record_pk>/services/<int:pk>/", MedicalRecordServiceDeleteView.as_view()),
    path("vaccines/", VaccineRecordListCreateView.as_view()),
    path("vaccines/<str:pk>/", VaccineRecordDetailView.as_view()),
]
