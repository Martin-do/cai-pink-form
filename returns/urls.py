from django.urls import path

from . import chancery_views, exports, views

urlpatterns = [
    # Priest portal
    path("portal/", views.my_dashboard, name="my_dashboard"),
    path("parishes/<int:parish_id>/returns/", views.parish_history, name="parish_history"),
    path("parishes/<int:parish_id>/returns/<int:period_id>/edit/", views.return_edit, name="return_edit"),
    path("returns/<int:pk>/", views.return_detail, name="return_detail"),
    path("returns/<int:pk>/pdf/", exports.export_return_pdf, name="return_pdf"),
    path("returns/<int:pk>/xlsx/", exports.export_return_xlsx, name="return_xlsx"),
    # Chancery portal
    path("chancery/", chancery_views.chancery_dashboard, name="chancery_dashboard"),
    path("chancery/annual/", chancery_views.annual_summary, name="annual_summary"),
    path("chancery/periods/<int:period_id>/xlsx/", exports.export_period_xlsx, name="period_xlsx"),
    path("chancery/returns/<int:pk>/unlock/", chancery_views.return_unlock, name="return_unlock"),
    path("chancery/returns/<int:pk>/accept/", chancery_views.return_accept, name="return_accept"),
    path("chancery/returns/<int:pk>/waive/", chancery_views.return_waive, name="return_waive"),
    path("chancery/returns/<int:pk>/payment/", chancery_views.return_payment, name="return_payment"),
    path("chancery/periods/", chancery_views.period_list, name="period_list"),
    path("chancery/periods/<int:pk>/toggle/", chancery_views.period_toggle, name="period_toggle"),
    path("chancery/line-items/", chancery_views.line_items, name="line_items"),
]
