from django.urls import path
from .views import (
    ServiceListCreateView,
    ServiceDetailView,
    InvoiceListCreateView,
    InvoiceDetailView,
    confirm_invoice,
    pay_invoice,
    direct_pay_invoice,
    cancel_invoice,
    refund_invoice,
    reverse_credit_note,
    invoice_pdf,
    InvoiceItemCreateView,
    InvoiceItemDetailView,
)

urlpatterns = [
    path('billing/services/', ServiceListCreateView.as_view()),
    path('billing/services/<str:pk>/', ServiceDetailView.as_view()),
    path('billing/invoices/', InvoiceListCreateView.as_view()),
    path('billing/invoices/<str:pk>/', InvoiceDetailView.as_view()),
    path('billing/invoices/<str:pk>/confirm/', confirm_invoice),
    path('billing/invoices/<str:pk>/pay/', pay_invoice),
    path('billing/invoices/<str:pk>/direct-pay/', direct_pay_invoice),
    path('billing/invoices/<str:pk>/cancel/', cancel_invoice),
    path('billing/invoices/<str:pk>/refund/', refund_invoice),
    path('billing/credit-notes/<str:pk>/reverse/', reverse_credit_note),
    path('billing/invoices/<str:pk>/pdf/', invoice_pdf),
    path('billing/invoices/<str:invoice_pk>/items/', InvoiceItemCreateView.as_view()),
    path('billing/invoices/<str:invoice_pk>/items/<int:pk>/', InvoiceItemDetailView.as_view()),
]
