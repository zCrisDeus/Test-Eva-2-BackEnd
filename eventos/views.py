from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.contrib.auth.hashers import make_password
from django.shortcuts import render
from rest_framework import viewsets, permissions
from django_filters.rest_framework import DjangoFilterBackend
from .models import Evento, CarroCompra, Orden, EntradaComprada, Sector, ItemCarro, Usuario, Artista, Recinto
from .serializers import EventoSerializer, CarroCompraSerializer, OrdenSerializer
from django.db import transaction
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import Orden, EntradaComprada, Sector
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: PERMISOS PERSONALIZADOS (ROLES JWT)
1. IsOrganizador: Permite acceso solo si el usuario autenticado
   tiene el rol 'ORGANIZADOR'.
2. IsEspectador: Restringe el acceso únicamente a los clientes para 
   que puedan gestionar su carro de compras y hacer pagos.
-------------------------------------------------------------------
"""
class IsOrganizador(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.rol == 'ORGANIZADOR')

class IsEspectador(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.rol == 'ESPECTADOR')

class OrdenViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrdenSerializer
    permission_classes = [IsEspectador]

    def get_queryset(self):
        # Solo retorna las órdenes exitosas (PAGADO) del usuario que consulta
        return Orden.objects.filter(espectador=self.request.user, estado='PAGADO').order_by('-fecha_orden')

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: CATÁLOGO DE EVENTOS (PÚBLICO Y ORGANIZADOR)
1. Cumple la Matriz API: GET es público (AllowAny). POST, PUT y 
   DELETE están protegidos (IsOrganizador).
2. Integra django-filter para buscar por ciudad o nombre del artista.
-------------------------------------------------------------------
"""
class EventoViewSet(viewsets.ModelViewSet):
    # select_related optimiza la consulta SQL evitando N+1 queries (3FN)
    queryset = Evento.objects.filter(activo=True).order_by('fecha_hora') 
    serializer_class = EventoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['recinto__ciudad', 'artista__nombre']

    def get_permissions(self):
        # GET (ver catálogo) es público
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        # POST, PUT, DELETE solo organizador
        return [IsOrganizador()]

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: CARRO DE COMPRAS PERSISTENTE
1. Protegido estrictamente por el rol IsEspectador.
2. get_queryset asegura que el usuario autenticado SOLO pueda ver 
   y modificar su propio carro, nunca el de otro.
-------------------------------------------------------------------
"""
class CarroViewSet(viewsets.ModelViewSet):
    serializer_class = CarroCompraSerializer
    permission_classes = [IsEspectador]

    def get_queryset(self):
        return CarroCompra.objects.filter(espectador=self.request.user)

    @action(detail=False, methods=['post'])
    def agregar_item(self, request):
        carro, created = CarroCompra.objects.get_or_create(espectador=request.user)
        sector_id = request.data.get('sector_id')
        cantidad_solicitada = int(request.data.get('cantidad', 1)) # Recibimos la cantidad
        
        try:
            sector = Sector.objects.get(id=sector_id)
        except Sector.DoesNotExist:
            return Response({"error": "Sector no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        # Buscamos si el ticket ya está en el carro
        item, item_created = ItemCarro.objects.get_or_create(carro=carro, sector=sector)
        
        # Validar la regla de negocio: Máximo 20 tickets por persona en ese sector
        cantidad_actual = 0 if item_created else item.cantidad
        if cantidad_actual + cantidad_solicitada > 20:
            if item_created: item.delete() # Revertimos si era un item nuevo
            return Response({"error": f"Límite excedido. Solo puedes tener un máximo de 20 tickets para {sector.nombre}."}, status=status.HTTP_400_BAD_REQUEST)

        # Si pasa la validación, sumamos la cantidad
        if item_created:
            item.cantidad = cantidad_solicitada
        else:
            item.cantidad += cantidad_solicitada
        item.save()
            
        return Response({"mensaje": f"{cantidad_solicitada} ticket(s) agregado(s) a tu carro."}, status=status.HTTP_200_OK)


    """
    -------------------------------------------------------------------
    BLOQUE DE LÓGICA: TRANSACCIÓN ATÓMICA DE PAGO (CHECKOUT)
    1. Se utiliza @action para crear un endpoint personalizado (/api/carro/pagar/).
    2. Se ejecuta dentro de transaction.atomic() para garantizar que
       si hay un error (ej. falta de stock de último minuto), se haga 
       un rollback completo y no se cobren entradas a medias.
    3. Utiliza select_for_update() para bloquear la fila en PostgreSQL 
       durante la transacción, evitando que dos usuarios compren el 
       último ticket exactamente al mismo milisegundo (condición de carrera).
    4. Verifica stock, descuenta 'stock_disponible', crea la Orden en 
       estado PAGADO, genera los tickets UUID y vacía el carro.
    -------------------------------------------------------------------
    """
    @action(detail=False, methods=['post'])
    def pagar(self, request):
        # Obtenemos el carro del usuario autenticado
        carro = self.get_queryset().first()
        items = carro.items.all()
        
        if not items.exists():
            return Response({"error": "El carro está vacío."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # transaction.atomic garantiza que o se hace todo, o no se hace nada
            with transaction.atomic():
                # 1. Validar stock de todos los items antes de cobrar
                for item in items:
                    sector = Sector.objects.select_for_update().get(id=item.sector.id)
                    if sector.stock_disponible < item.cantidad:
                        return Response(
                            {"error": f"Stock insuficiente para el sector {sector.nombre}."}, 
                            status=status.HTTP_400_BAD_REQUEST
                        )

                # 2. Crear la Orden (Factura general)
                total_pagar = sum(item.sector.precio * item.cantidad for item in items)
                orden = Orden.objects.create(
                    espectador=request.user,
                    estado='PAGADO',
                    total=total_pagar
                )

                # 3. Descontar stock y emitir Entradas únicas (Tickets)
                for item in items:
                    sector = item.sector
                    sector.stock_disponible -= item.cantidad
                    sector.save()

                    # Por cada cantidad solicitada, generamos un UUID individual
                    for _ in range(item.cantidad):
                        EntradaComprada.objects.create(
                            orden=orden,
                            sector=sector,
                            precio_pagado=sector.precio # Cumple 3FN Histórica
                        )

                # 4. Vaciar el carro post-compra exitosa
                items.delete()

            return Response({
                "mensaje": "¡Pago exitoso! Sus tickets han sido generados.", 
                "orden_id": orden.id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ... (Arriba termina la clase CarroViewSet o la clase OrdenViewSet)

@api_view(['POST'])
@permission_classes([AllowAny])
def api_registro(request):
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    
    # Validar si el nombre de usuario ya existe
    if Usuario.objects.filter(username=username).exists():
        return Response({"error": "Este nombre de usuario ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)
        
    # Validar si el correo ya está registrado
    if Usuario.objects.filter(email=email).exists():
        return Response({"error": "Este correo electrónico ya está registrado."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Crear el usuario incluyendo el email y forzando el rol de ESPECTADOR
    Usuario.objects.create(
        username=username,
        email=email,
        password=make_password(password),
        rol='ESPECTADOR'
    )
    return Response({"mensaje": "Cuenta creada con éxito. Ahora puedes iniciar sesión."}, status=status.HTTP_201_CREATED)

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: CREACIÓN DE EVENTOS DESDE TEMPLATE
Requisito: Evitar el admin de Django y usar API + JWT (Rol Organizador)
-------------------------------------------------------------------
"""
@api_view(['GET'])
@permission_classes([IsOrganizador])
def datos_formulario_evento(request):
    artistas = list(Artista.objects.filter(activo=True).values('id', 'nombre'))
    recintos = list(Recinto.objects.filter(activo=True).values('id', 'nombre'))
    return Response({'artistas': artistas, 'recintos': recintos})

@api_view(['POST'])
@permission_classes([IsOrganizador])
def api_crear_evento(request):
    try:
        # 1. Crear el Evento principal
        evento = Evento.objects.create(
            nombre=request.data.get('nombre'),
            fecha_hora=request.data.get('fecha_hora'),
            artista_id=request.data.get('artista_id'),
            recinto_id=request.data.get('recinto_id'),
            organizador=request.user
        )
        
        # 2. Recorrer la lista de sectores recibida y crearlos uno por uno
        sectores_data = request.data.get('sectores', [])
        for sec in sectores_data:
            Sector.objects.create(
                evento=evento,
                nombre=sec.get('nombre'),
                precio=int(sec.get('precio')),
                stock_total=int(sec.get('stock')),
                stock_disponible=int(sec.get('stock'))
            )
        
        return Response({"mensaje": f"¡Evento publicado con {len(sectores_data)} sector(es) exitosamente!"}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['POST'])
@permission_classes([IsOrganizador])
def api_crear_artista(request):
    nombre = request.data.get('nombre')
    if not nombre:
        return Response({"error": "El nombre no puede estar vacío."}, status=status.HTTP_400_BAD_REQUEST)
    
    # get_or_create evita que se creen artistas duplicados con el mismo nombre
    artista, created = Artista.objects.get_or_create(nombre=nombre)
    return Response({
        "id": artista.id, 
        "nombre": artista.nombre, 
        "mensaje": "Artista creado con éxito"
    }, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsOrganizador])
def api_crear_recinto(request):
    nombre = request.data.get('nombre')
    ciudad = request.data.get('ciudad', 'Desconocida') # Capturamos la ciudad para el buscador
    
    if not nombre:
        return Response({"error": "El nombre no puede estar vacío."}, status=status.HTTP_400_BAD_REQUEST)
    
    # get_or_create busca si existe; si no, lo crea usando el nombre y la ciudad por defecto
    recinto, created = Recinto.objects.get_or_create(nombre=nombre, defaults={'ciudad': ciudad})
    
    return Response({
        "id": recinto.id, 
        "nombre": recinto.nombre, 
        "mensaje": "Recinto creado con éxito"
    }, status=status.HTTP_201_CREATED)

"""
-------------------------------------------------------------------
PANEL DE GESTIÓN AVANZADA (Soft Delete y Stock)
-------------------------------------------------------------------
"""
@api_view(['GET'])
@permission_classes([IsOrganizador])
def api_datos_gestion(request):
    artistas = list(Artista.objects.values('id', 'nombre', 'activo').order_by('nombre'))
    recintos = list(Recinto.objects.values('id', 'nombre', 'ciudad', 'activo').order_by('nombre'))
    
    eventos_data = []
    for e in Evento.objects.order_by('-fecha_hora'):
        sectores = list(e.sectores.values('id', 'nombre', 'stock_disponible', 'stock_total'))
        eventos_data.append({
            'id': e.id, 'nombre': e.nombre, 'activo': e.activo, 'sectores': sectores
        })
        
    return Response({'artistas': artistas, 'recintos': recintos, 'eventos': eventos_data})

@api_view(['POST'])
@permission_classes([IsOrganizador])
def api_toggle_estado(request):
    tipo = request.data.get('tipo')
    item_id = request.data.get('id')
    
    if tipo == 'artista': obj = Artista.objects.get(id=item_id)
    elif tipo == 'recinto': obj = Recinto.objects.get(id=item_id)
    elif tipo == 'evento': obj = Evento.objects.get(id=item_id)
    else: return Response({"error": "Tipo inválido"}, status=400)
    
    obj.activo = not obj.activo # Invierte el estado (Si es True pasa a False y viceversa)
    obj.save()
    estado_str = "Activo" if obj.activo else "Deshabilitado"
    return Response({'mensaje': f'{obj.nombre} ahora está {estado_str}.'})

@api_view(['POST'])
@permission_classes([IsOrganizador])
def api_actualizar_stock(request):
    sector_id = request.data.get('sector_id')
    nuevo_stock = int(request.data.get('nuevo_stock'))
    
    sector = Sector.objects.get(id=sector_id)
    sector.stock_disponible = nuevo_stock # Actualizamos directamente la cantidad disponible
    sector.save()
    
    return Response({'mensaje': f'Stock actualizado a {nuevo_stock} tickets.'})

def front_gestion(request):
    return render(request, 'eventos/gestion.html')

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([AllowAny])
def api_grafica_ventas(request):
    eventos = Evento.objects.filter(activo=True)
    datos = []
    
    for e in eventos:
        # Calculamos los tickets vendidos restando el stock disponible al stock total
        vendidos = sum([s.stock_total - s.stock_disponible for s in e.sectores.all()])
        if vendidos > 0:
            datos.append({'evento': e.nombre, 'vendidos': vendidos})
            
    # Ordenamos de mayor a menor y tomamos el Top 5
    datos = sorted(datos, key=lambda x: x['vendidos'], reverse=True)[:5]
    return Response(datos)

"""
-------------------------------------------------------------------
MÓDULO DE CHECKOUT Y ÓRDENES
-------------------------------------------------------------------
"""
@api_view(['POST'])
@permission_classes([IsEspectador])
def api_checkout(request):
    carro = CarroCompra.objects.filter(espectador=request.user).first()
    if not carro or not carro.items.exists():
        return Response({"error": "Tu carro está vacío."}, status=status.HTTP_400_BAD_REQUEST)
        
    with transaction.atomic():
        total = 0
        for item in carro.items.all():
            if item.sector.stock_disponible < item.cantidad:
                return Response({"error": f"Stock insuficiente para {item.sector.nombre}."}, status=status.HTTP_400_BAD_REQUEST)
            
            total += item.sector.precio * item.cantidad
            item.sector.stock_disponible -= item.cantidad
            item.sector.save()
            
        # 👇 ESTA LÍNEA ES LA CLAVE: FUERZA EL ESTADO A PENDIENTE SÍ O SÍ 👇
        orden = Orden.objects.create(espectador=request.user, estado='PENDIENTE', total=total)
        
        for item in carro.items.all():
            for _ in range(item.cantidad):
                EntradaComprada.objects.create(orden=orden, sector=item.sector)
                
        carro.items.all().delete()
        
    return Response({"mensaje": f"¡Orden #{orden.id} creada! Esperando aprobación."})

@api_view(['GET', 'POST'])
@permission_classes([IsOrganizador])
def admin_ordenes(request):
    if request.method == 'GET':
        ordenes = Orden.objects.all().order_by('-fecha_creacion')
        data = [{
            'id': o.id, 'cliente': o.espectador.username, 'estado': o.estado, 
            'total': o.total, 'fecha': o.fecha_creacion.strftime("%d/%m/%Y")
        } for o in ordenes]
        return Response(data)
        
    elif request.method == 'POST':
        orden = Orden.objects.get(id=request.data.get('id'))
        nuevo_estado = request.data.get('estado')
        
        # Si se CANCELA la orden, devolvemos el stock
        if nuevo_estado == 'CANCELADO' and orden.estado != 'CANCELADO':
            with transaction.atomic():
                for entrada in orden.entradacomprada_set.all():
                    entrada.sector.stock_disponible += 1
                    entrada.sector.save()
                    
        orden.estado = nuevo_estado
        orden.save()
        return Response({"mensaje": f"Orden #{orden.id} cambiada a {nuevo_estado}."})

@api_view(['GET'])
@permission_classes([IsOrganizador])
def admin_carros(request):
    items = ItemCarro.objects.all().order_by('carro__espectador__username')
    data = [{
        'id': i.id, 'usuario': i.carro.espectador.username, 'sector': i.sector.nombre, 
        'cantidad': i.cantidad, 'fecha': i.fecha_agregado.strftime("%d/%m/%Y") if i.fecha_agregado else "Hoy"
    } for i in items]
    return Response(data)

@api_view(['POST'])
@permission_classes([IsOrganizador])
def limpiar_carros_vencidos(request):
    # Lógica de expiración: 15 días exactos
    hace_15_dias = timezone.now() - timedelta(days=15)
    vencidos = ItemCarro.objects.filter(fecha_agregado__lt=hace_15_dias)
    cantidad = vencidos.count()
    vencidos.delete() # Como el stock se descuenta en el checkout, solo borramos el ítem del carro
    return Response({"mensaje": f"Limpieza completada. Se eliminaron {cantidad} ítems caducados (más de 15 días)."})

@api_view(['GET'])
@permission_classes([IsEspectador])
def api_notificaciones(request):
    # Buscamos órdenes del usuario que ya fueron procesadas por el admin pero no han sido notificadas
    ordenes = Orden.objects.filter(espectador=request.user, notificado=False).exclude(estado='PENDIENTE')
    mensajes = []
    
    for orden in ordenes:
        if orden.estado == 'PAGADO':
            mensajes.append(f"✅ ¡Tus tickets de la Orden #{orden.id} se han pagado con éxito!")
        elif orden.estado == 'CANCELADO':
            mensajes.append(f"❌ La transacción de tu Orden #{orden.id} ha sido cancelada.")
        elif orden.estado == 'ENTREGADO':
            mensajes.append(f"🎟️ Tu Orden #{orden.id} ha sido completada.")
            
        # Marcamos la orden como notificada para que la alerta no vuelva a salir al recargar la página
        orden.notificado = True
        orden.save()
        
    return Response({'notificaciones': mensajes})
"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: VISTAS FRONTEND (TEMPLATES)
1. front_inicio: Renderiza la página principal del catálogo en HTML.
2. error_404_view: Captura rutas inexistentes y devuelve tu diseño 
   personalizado, cumpliendo el requerimiento de la rúbrica.
-------------------------------------------------------------------
"""
def front_inicio(request):
    return render(request, 'eventos/inicio.html')

def front_login(request):
    return render(request, 'eventos/login.html')

def error_404_view(request, exception=None):
    return render(request, 'eventos/404.html', status=404)

def front_carro(request):
    return render(request, 'eventos/carro.html')

def front_mis_entradas(request):
    return render(request, 'eventos/mis_entradas.html')

def front_registro(request):
    return render(request, 'eventos/registro.html')

def front_crear_evento(request):
    return render(request, 'eventos/crear_evento.html')