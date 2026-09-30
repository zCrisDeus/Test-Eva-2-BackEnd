from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: MODELO DE USUARIO (ROLES JWT)
1. Hereda de AbstractUser para extender el usuario nativo de Django.
2. Implementa la propiedad CHOICES exigida en la rúbrica para 
   definir si es ESPECTADOR u ORGANIZADOR.
-------------------------------------------------------------------
"""
class Usuario(AbstractUser):
    ROLES = (
        ('ESPECTADOR', 'Espectador'),
        ('ORGANIZADOR', 'Organizador de Eventos'),
    )
    rol = models.CharField(max_length=20, choices=ROLES, default='ESPECTADOR')

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: TABLAS INDEPENDIENTES (3FN)
1. Recinto y Artista se separan de Evento para cumplir con la 3FN.
-------------------------------------------------------------------
"""
class Recinto(models.Model):
    nombre = models.CharField(max_length=200)
    direccion = models.CharField(max_length=200)
    ciudad = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)
    
    def __str__(self):
        return self.nombre

class Artista(models.Model):
    nombre = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)
    genero_musical = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.nombre

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: EVENTOS Y SECTORES
1. Evento agrupa las ForeignKeys garantizando integridad referencial.
2. Sector maneja el stock de entradas y precios por localidad.
-------------------------------------------------------------------
"""
class Evento(models.Model):
    nombre = models.CharField(max_length=200)
    fecha_hora = models.DateTimeField()
    organizador = models.ForeignKey(Usuario, on_delete=models.CASCADE, limit_choices_to={'rol': 'ORGANIZADOR'})
    recinto = models.ForeignKey(Recinto, on_delete=models.PROTECT)
    artista = models.ForeignKey(Artista, on_delete=models.PROTECT)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class Sector(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='sectores')
    nombre = models.CharField(max_length=200) 
    precio = models.IntegerField()
    stock_total = models.PositiveIntegerField()
    stock_disponible = models.PositiveIntegerField() 

    def __str__(self):
        return f"{self.nombre} - {self.evento.nombre}"

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: CARRO DE COMPRAS PERSISTENTE
1. Cumple el requerimiento de relación 1 a 1 entre Usuario y Carro.
2. Los items agregados persisten en PostgreSQL aunque se cierre sesión.
-------------------------------------------------------------------
"""
class CarroCompra(models.Model):
    espectador = models.OneToOneField(Usuario, on_delete=models.CASCADE, limit_choices_to={'rol': 'ESPECTADOR'})
    fecha_creacion = models.DateTimeField(auto_now_add=True)

class ItemCarro(models.Model):
    carro = models.ForeignKey(CarroCompra, on_delete=models.CASCADE, related_name='items')
    sector = models.ForeignKey(Sector, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=1)
    fecha_agregado = models.DateTimeField(auto_now_add=True, null=True)

"""
-------------------------------------------------------------------
BLOQUE DE LÓGICA: TRANSACCIONES, ESTADOS Y TICKETS
1. Orden implementa la propiedad CHOICES (PENDIENTE/PAGADO/CANCELADO).
2. EntradaComprada genera un UUID único por ticket y guarda precio_pagado
   para mantener la 3FN histórica (si el sector sube de precio mañana,
   esta entrada mantiene el precio al que fue comprada).
-------------------------------------------------------------------
"""
class Orden(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('ENTREGADO', 'Entregado/Completado'),
        ('CANCELADO', 'Cancelado'),
    ]
    espectador = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    total = models.IntegerField(default=0)
    notificado = models.BooleanField(default=False)

class EntradaComprada(models.Model):
    codigo_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    orden = models.ForeignKey(Orden, on_delete=models.CASCADE, related_name='entradas')
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT)
    precio_pagado = models.IntegerField() 

    def __str__(self):
        return str(self.codigo_uuid)