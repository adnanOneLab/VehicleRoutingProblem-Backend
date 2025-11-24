from django.urls import path
from . import views

urlpatterns = [
    path('solve', views.solve_vrp, name='solve_vrp'),
    path('solve-pdp', views.solve_pdp, name='solve_pdp'),  # New PDP endpoint
    path('solution/<str:solution_id>', views.get_vrp_solution, name='get_vrp_solution'),
    path('config', views.save_vrp_config, name='save_vrp_config'),
    path('configs', views.get_vrp_configs, name='get_vrp_configs'),
    path('config/<int:config_id>', views.delete_vrp_config, name='delete_vrp_config'),
    path('validate', views.validate_vrp, name='validate_vrp'),
    path('google-maps-distance-matrix', views.google_maps_distance_matrix, name='google_maps_distance_matrix'),
]