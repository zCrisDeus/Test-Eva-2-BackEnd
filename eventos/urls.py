from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from .serializers import CustomTokenObtainPairView
from .views import EventoViewSet, CarroViewSet, front_inicio, front_login, front_carro, OrdenViewSet, front_mis_entradas, api_registro, front_registro, datos_formulario_evento, api_crear_evento, front_crear_evento, api_crear_artista, api_crear_recinto, api_datos_gestion, api_toggle_estado, api_actualizar_stock, front_gestion, api_grafica_ventas,api_checkout, admin_ordenes, admin_carros, limpiar_carros_vencidos, api_notificaciones
router = DefaultRouter()
router.register(r'eventos', EventoViewSet, basename='evento')
router.register(r'carro', CarroViewSet, basename='carro')
router.register(r'ordenes', OrdenViewSet, basename='orden')

urlpatterns = [
    # --- 1. RUTAS FRONTEND (Templates) ---
    path('', front_inicio, name='inicio'),
    path('login/', front_login, name='login'),
    path('registro/', front_registro, name='registro'), # <-- Ruta HTML registro
    path('carro/', front_carro, name='carro'),
    path('mis-entradas/', front_mis_entradas, name='mis_entradas'),
    path('crear-evento/', front_crear_evento, name='crear_evento'),
    path('gestion/', front_gestion, name='gestion'),

    # --- 2. RUTAS API (Backend) ---
    path('api/', include(router.urls)),
    path('api/registro/', api_registro, name='api_registro'),
    path('api/datos-formulario/', datos_formulario_evento, name='datos_formulario'),
    path('api/crear-evento/', api_crear_evento, name='api_crear_evento'),
    path('api/crear-artista/', api_crear_artista, name='api_crear_artista'),
    path('api/crear-recinto/', api_crear_recinto, name='api_crear_recinto'),
    path('api/gestion/datos/', api_datos_gestion, name='api_datos_gestion'),
    path('api/gestion/toggle/', api_toggle_estado, name='api_toggle_estado'),
    path('api/gestion/stock/', api_actualizar_stock, name='api_actualizar_stock'),
    path('api/estadisticas/ventas/', api_grafica_ventas, name='api_grafica_ventas'),
    path('api/checkout/', api_checkout, name='api_checkout'),
    path('api/admin/ordenes/', admin_ordenes, name='admin_ordenes'),
    path('api/admin/carros/', admin_carros, name='admin_carros'),
    path('api/admin/carros/limpiar/', limpiar_carros_vencidos, name='limpiar_carros'),
    path('api/notificaciones/', api_notificaciones, name='api_notificaciones'),
    
    # --- 3. RUTAS SEGURIDAD (JWT) ---
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # --- 4. DOCUMENTACIÓN SWAGGER ---
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]